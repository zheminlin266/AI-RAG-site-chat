"""
RAG engine — multi-format document loading, chunking, embedding, retrieval.

Embeddings via OpenRouter API (no local model download needed).
Default: openai/text-embedding-3-small (1536-dim, $0.02/1M tokens).

Data flow:
  Docs → Chunks → OpenRouter Embed API → ChromaDB
  Query → Hybrid (Vector + BM25 + RRF) → Filtered Top-K Chunks

Retrieval strategy:
  - Vector search (semantic) + BM25 (keyword) → Reciprocal Rank Fusion
  - Cosine distance threshold filters out irrelevant chunks
  - No LLM re-ranking — RRF alone provides sufficient precision
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
import threading
from typing import Iterator, TypedDict
from uuid import uuid4

import chromadb
import httpx
from rank_bm25 import BM25Okapi

import backend.config as _cfg

from backend.parsers import (
    load_markdown_files,
    load_html_files,
    load_json_files,
    load_text_files,
)

logger = logging.getLogger(__name__)

# ── 类型 ────────────────────────────────────────────


class Chunk(TypedDict):
    id: str
    text: str
    metadata: dict[str, str]


# ── ChromaDB（单例） ────────────────────────────────

_chroma_client: chromadb.PersistentClient | None = None
_collection: chromadb.Collection | None = None
_active_collection_name: str | None = None

# Rebuilds populate a complete staging collection before switching this pointer.
# Existing searches retain a read lease on the old collection until they finish.
_state_lock = threading.RLock()
_build_lock = threading.Lock()
_active_readers: Counter[str] = Counter()
_retired_collections: set[str] = set()
_DEFAULT_COLLECTION = "knowledge"
_STAGING_PREFIX = "knowledge-staging-"


def _active_index_file() -> Path:
    return _cfg.CHROMA_DB_DIR / "active_index.json"


def _valid_collection_name(name: object) -> bool:
    return isinstance(name, str) and (
        name == _DEFAULT_COLLECTION
        or (
            name.startswith(_STAGING_PREFIX)
            and len(name) == len(_STAGING_PREFIX) + 32
            and all(char in "0123456789abcdef" for char in name[len(_STAGING_PREFIX) :])
        )
    )


def _read_active_collection_name() -> str:
    try:
        payload = json.loads(_active_index_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _DEFAULT_COLLECTION
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("Ignoring invalid active index pointer: %s", error)
        return _DEFAULT_COLLECTION

    name = payload.get("collection") if isinstance(payload, dict) else None
    if _valid_collection_name(name):
        return name
    logger.warning("Ignoring invalid active index collection name: %r", name)
    return _DEFAULT_COLLECTION


def _write_active_collection_name(name: str) -> None:
    if not _valid_collection_name(name):
        raise RuntimeError("Refusing to persist an invalid collection name")
    index_file = _active_index_file()
    index_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = index_file.with_name(f".{index_file.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps({"collection": name}), encoding="utf-8")
        os.replace(temporary, index_file)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=str(_cfg.CHROMA_DB_DIR))
    return _chroma_client


def _open_active_collection_locked() -> chromadb.Collection:
    global _collection, _active_collection_name
    if _collection is not None:
        return _collection

    client = _get_chroma_client()
    name = _active_collection_name or _read_active_collection_name()
    try:
        if name == _DEFAULT_COLLECTION:
            collection = client.get_or_create_collection(
                name=name, metadata={"hnsw:space": "cosine"}
            )
        else:
            collection = client.get_collection(name=name)
    except Exception as error:
        if name == _DEFAULT_COLLECTION:
            raise
        logger.warning(
            "Active collection %s could not be opened (%s); falling back to %s",
            name,
            error,
            _DEFAULT_COLLECTION,
        )
        name = _DEFAULT_COLLECTION
        collection = client.get_or_create_collection(
            name=name, metadata={"hnsw:space": "cosine"}
        )

    _collection = collection
    _active_collection_name = name
    return collection


def _get_collection() -> chromadb.Collection:
    with _state_lock:
        return _open_active_collection_locked()


# ── BM25 索引（单例） ───────────────────────────────
# ponytail: 全量存储在内存中。O(n) 内存 ≈ chunk 数 × 平均词数。
# 对于 50K 以下 chunk 没问题；超过 100K 建议换用磁盘 BM25（tantivy）。

_bm25_index: BM25Okapi | None = None
_bm25_chunk_ids: list[str] = []  # 与 BM25 索引排序一致的 chunk ID 列表
_all_chunks: dict[str, Chunk] = {}  # chunk_id → Chunk 全量映射（用于 BM25 命中回查）


@contextmanager
def _active_state() -> Iterator[
    tuple[chromadb.Collection, str, BM25Okapi | None, list[str], dict[str, Chunk]]
]:
    """Take a read lease so a completed search never loses its collection."""
    with _state_lock:
        collection = _open_active_collection_locked()
        name = _active_collection_name
        if name is None:  # Defensive: _open_active_collection_locked sets this.
            raise RuntimeError("No active Chroma collection")
        _active_readers[name] += 1
        bm25 = _bm25_index
        bm25_ids = _bm25_chunk_ids[:]
        chunks = _all_chunks.copy()

    try:
        yield collection, name, bm25, bm25_ids, chunks
    finally:
        _release_collection_lease(name)


def _release_collection_lease(name: str) -> None:
    delete_name: str | None = None
    with _state_lock:
        _active_readers[name] -= 1
        if _active_readers[name] <= 0:
            _active_readers.pop(name, None)
            if name in _retired_collections:
                _retired_collections.remove(name)
                delete_name = name
    if delete_name:
        _delete_collection(delete_name)


def _delete_collection(name: str) -> None:
    try:
        _get_chroma_client().delete_collection(name=name)
        logger.info("Deleted retired Chroma collection: %s", name)
    except Exception as error:
        # A failed cleanup is safe: the active pointer still names the new index.
        logger.warning("Could not delete retired collection %s: %s", name, error)


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer for Chinese + English. No external NLP deps.

    Strategy:
    - English/numbers: whitespace splitting, lowercased
    - Chinese: character bigrams for partial matching (standard approach
      for Chinese BM25 without a segmenter like jieba)
    - Punctuation stripped
    """
    import re

    tokens: list[str] = []

    # Split into Chinese runs vs non-Chinese runs
    segments = re.split(r"([\u4e00-\u9fff]+)", text)
    for seg in segments:
        if not seg.strip():
            continue
        if re.match(r"[\u4e00-\u9fff]+", seg):
            # Chinese: character bigrams for partial match
            chars = list(seg)
            for i in range(len(chars)):
                tokens.append(chars[i])
                if i < len(chars) - 1:
                    tokens.append(chars[i] + chars[i + 1])
        else:
            # English/numbers: whitespace tokenize, lowercase, strip punct
            for word in seg.split():
                cleaned = word.strip(".,;:!?()[]{}'\"-").lower()
                if cleaned:
                    tokens.append(cleaned)

    return [t for t in tokens if t.strip()]


# ── 嵌入：通过 OpenRouter API ────────────────────────


def _embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """
    Get embeddings via OpenRouter API.

    ponytail: single HTTP call, no retry. For batch indexing,
    chunks are sent in sub-batches to avoid timeout/memory issues.
    API: https://openrouter.ai/docs/features/embeddings
    """
    if not texts:
        return []

    api_key = _cfg.OPENROUTER_API_KEY
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set — cannot generate embeddings")

    embedding_model = model or _cfg.EMBEDDING_MODEL
    client = httpx.Client(timeout=120.0)

    try:
        resp = client.post(
            "https://openrouter.ai/api/v1/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": embedding_model, "input": texts},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Embedding API returned {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        # Sort by index to preserve input order
        sorted_data = sorted(data["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in sorted_data]

    finally:
        client.close()


def _embed_in_batches(
    texts: list[str],
    batch_size: int = 50,
    model: str | None = None,
) -> list[list[float]]:
    """
    Generate embeddings in batches to avoid API timeouts.
    Returns embeddings in the same order as input texts.
    """
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        logger.info(f"  Embedding batch {i // batch_size + 1}: {len(batch)} texts...")
        embeddings = _embed(batch, model=model)
        all_embeddings.extend(embeddings)
    return all_embeddings


# ── 文档加载 ────────────────────────────────────────


def _load_all_documents(directory: Path) -> list[dict]:
    """Load all supported document types."""
    all_files: list[dict] = []

    loaders: list[tuple[str, callable]] = [
        ("Markdown", load_markdown_files),
        ("HTML", load_html_files),
        ("JSON", load_json_files),
        ("Text", load_text_files),
    ]

    for label, loader in loaders:
        try:
            files = loader(directory)
            logger.info(f"  {label}: {len(files)} files")
            all_files.extend(files)
        except Exception as e:
            logger.warning(f"  {label}: skipped ({e})")

    return all_files


# ── 分块 ────────────────────────────────────────────


def _split_into_chunks(
    text: str,
    source: str,
    chunk_size: int = _cfg.CHUNK_SIZE,
    overlap: int = _cfg.CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split text into chunks by headings, then sentences for long sections."""
    chunks: list[Chunk] = []
    sections = _split_by_headings(text)

    for heading, section_text in sections:
        est_tokens = _estimate_tokens(section_text)

        if est_tokens <= chunk_size:
            chunks.append(Chunk(
                id=_make_chunk_id(source, heading, section_text),
                text=f"{heading}\n\n{section_text}".strip() if heading else section_text.strip(),
                metadata={"source": source, "heading": heading or ""},
            ))
        else:
            chunks.extend(
                _split_long_section(heading, section_text, source, chunk_size, overlap)
            )

    return chunks


def _split_by_headings(text: str) -> list[tuple[str, str]]:
    import re
    pattern = r"^#{1,3}\s+.+$"
    lines = text.split("\n")
    sections: list[tuple[str, str]] = []
    current_heading = ""
    current_body: list[str] = []

    for line in lines:
        if re.match(pattern, line):
            if current_body:
                body = "\n".join(current_body).strip()
                if body:
                    sections.append((current_heading, body))
            current_heading = line.strip()
            current_body = []
        else:
            current_body.append(line)

    if current_body:
        body = "\n".join(current_body).strip()
        if body:
            sections.append((current_heading, body))

    if not sections:
        sections.append(("", text.strip()))

    return sections


def _split_long_section(
    heading: str, text: str, source: str, chunk_size: int, overlap: int
) -> list[Chunk]:
    import re
    sentences = re.split(r"(?<=[。！？.!?\n])\s*", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[Chunk] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sent_tokens = _estimate_tokens(sentence)
        if current_tokens + sent_tokens > chunk_size and current:
            chunk_text = "\n".join(current)
            part_label = f" (part {len(chunks) + 1})"
            full_heading = f"{heading}{part_label}" if heading else f"(part {len(chunks) + 1})"
            chunks.append(Chunk(
                id=_make_chunk_id(source, heading, chunk_text),
                text=f"{full_heading}\n\n{chunk_text}".strip(),
                metadata={"source": source, "heading": heading or ""},
            ))
            current = _calc_overlap_sentences(current, overlap)
            current_tokens = sum(_estimate_tokens(s) for s in current)

        current.append(sentence)
        current_tokens += sent_tokens

    if current:
        chunk_text = "\n".join(current)
        full_heading = f"{heading} (part {len(chunks) + 1})" if (heading and chunks) else heading
        chunks.append(Chunk(
            id=_make_chunk_id(source, heading, chunk_text),
            text=f"{full_heading}\n\n{chunk_text}".strip() if full_heading else chunk_text.strip(),
            metadata={"source": source, "heading": heading or ""},
        ))

    return chunks


def _calc_overlap_sentences(sentences: list[str], overlap_tokens: int) -> list[str]:
    result: list[str] = []
    total = 0
    for s in reversed(sentences):
        total += _estimate_tokens(s)
        result.insert(0, s)
        if total >= overlap_tokens:
            break
    return result


def _estimate_tokens(text: str) -> int:
    chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    english_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + english_chars / 4)


def _make_chunk_id(source: str, heading: str, text: str) -> str:
    """Generate stable chunk ID from content hash. Uses full text to avoid collisions."""
    raw = f"{source}|{heading}|{text}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


# ── Reciprocal Rank Fusion ──────────────────────────


def _rrf_fusion(
    vector_results: list[tuple[str, float]],
    bm25_results: list[tuple[str, float]],
    k: int = 60,
) -> list[str]:
    """
    Merge two ranked lists via Reciprocal Rank Fusion.

    score(chunk) = Σ 1 / (k + rank_in_list_i)

    k=60 is the standard value from the original RRF paper.
    Returns chunk IDs sorted by descending fused score.
    """
    scores: dict[str, float] = {}

    for rank, (chunk_id, _score) in enumerate(vector_results):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)

    for rank, (chunk_id, _score) in enumerate(bm25_results):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)

    sorted_pairs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [cid for cid, _ in sorted_pairs]


# ── 公共 API ────────────────────────────────────────


def _bm25_state(
    ids: list[str], docs: list[str], metas: list[dict[str, str]]
) -> tuple[BM25Okapi, list[str], dict[str, Chunk]]:
    if not ids:
        raise RuntimeError("Cannot build a BM25 index without chunks")
    return (
        BM25Okapi([_tokenize(document) for document in docs]),
        ids[:],
        {
            chunk_id: Chunk(id=chunk_id, text=document, metadata=metadata)
            for chunk_id, document, metadata in zip(ids, docs, metas)
        },
    )


def _bm25_state_from_collection(
    collection: chromadb.Collection,
) -> tuple[BM25Okapi, list[str], dict[str, Chunk]]:
    all_data = collection.get(include=["documents", "metadatas"])
    ids = list(all_data.get("ids") or [])
    if not ids:
        raise RuntimeError("Cannot build BM25 from an empty collection")

    raw_docs = all_data.get("documents") or [""] * len(ids)
    raw_metas = all_data.get("metadatas") or [{}] * len(ids)
    docs = [document if isinstance(document, str) else "" for document in raw_docs]
    metas = [metadata if isinstance(metadata, dict) else {} for metadata in raw_metas]
    return _bm25_state(ids, docs, metas)


def _set_bm25_state_if_active(
    collection_name: str,
    bm25: BM25Okapi,
    ids: list[str],
    chunks: dict[str, Chunk],
) -> None:
    global _bm25_index, _bm25_chunk_ids, _all_chunks
    with _state_lock:
        if _active_collection_name == collection_name:
            _bm25_index = bm25
            _bm25_chunk_ids = ids
            _all_chunks = chunks


def _activate_staging_collection(
    collection: chromadb.Collection,
    name: str,
    bm25: BM25Okapi,
    bm25_ids: list[str],
    chunks: dict[str, Chunk],
) -> None:
    """Persist the new pointer before exposing the new index to readers."""
    global _collection, _active_collection_name, _bm25_index, _bm25_chunk_ids, _all_chunks

    _write_active_collection_name(name)
    delete_name: str | None = None
    with _state_lock:
        old_name = _active_collection_name
        _collection = collection
        _active_collection_name = name
        _bm25_index = bm25
        _bm25_chunk_ids = bm25_ids
        _all_chunks = chunks

        if old_name and old_name != name:
            if _active_readers.get(old_name, 0):
                _retired_collections.add(old_name)
            else:
                delete_name = old_name

    if delete_name:
        _delete_collection(delete_name)


def _deduplicated_chunks(files: list[dict]) -> tuple[list[str], list[str], list[dict[str, str]]]:
    seen: set[str] = set()
    ids: list[str] = []
    texts: list[str] = []
    metas: list[dict[str, str]] = []

    for file_data in files:
        for chunk in _split_into_chunks(file_data["content"], file_data["path"]):
            if chunk["id"] in seen:
                continue
            seen.add(chunk["id"])
            ids.append(chunk["id"])
            texts.append(chunk["text"])
            metas.append(chunk["metadata"])
    return ids, texts, metas


def build_index(force: bool = False) -> int:
    """Build a complete staged index and switch to it only after success."""
    with _build_lock:
        with _active_state() as (active_collection, active_name, current_bm25, _, _):
            existing = active_collection.count()

        if existing and not force:
            if current_bm25 is None:
                logger.info("Index has %s chunks; rebuilding its BM25 index...", existing)
                bm25, bm25_ids, chunks = _bm25_state_from_collection(active_collection)
                _set_bm25_state_if_active(active_name, bm25, bm25_ids, chunks)
            else:
                logger.info("Index has %s chunks; skipping rebuild", existing)
            return existing

        files = _load_all_documents(_cfg.KNOWLEDGE_BASE_DIR)
        if not files:
            message = f"No documents found in {_cfg.KNOWLEDGE_BASE_DIR}"
            if existing:
                raise RuntimeError(f"{message}; the existing index was kept")
            logger.warning(message)
            return 0

        ids, texts, metas = _deduplicated_chunks(files)
        if not ids:
            message = "No indexable document chunks were produced"
            if existing:
                raise RuntimeError(f"{message}; the existing index was kept")
            logger.warning(message)
            return 0

        logger.info("Generating embeddings for %s chunks via OpenRouter...", len(texts))
        embeddings = _embed_in_batches(texts, batch_size=50)
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"Embedding API returned {len(embeddings)} vectors for {len(texts)} chunks"
            )
        bm25, bm25_ids, chunks = _bm25_state(ids, texts, metas)

        staging_name = f"{_STAGING_PREFIX}{uuid4().hex}"
        staging = _get_chroma_client().create_collection(
            name=staging_name, metadata={"hnsw:space": "cosine"}
        )
        try:
            staging.add(
                ids=ids,
                embeddings=embeddings,  # type: ignore[arg-type]
                documents=texts,
                metadatas=metas,  # type: ignore[arg-type]
            )
            _activate_staging_collection(staging, staging_name, bm25, bm25_ids, chunks)
        except Exception:
            # The active collection remains untouched until _activate succeeds.
            _delete_collection(staging_name)
            raise

        logger.info("Index built and activated: %s chunks", len(ids))
        return len(ids)


def _positive_bm25_results(
    bm25: BM25Okapi | None,
    chunk_ids: list[str],
    query_tokens: list[str],
    candidate_k: int,
) -> list[tuple[str, float]]:
    """Rank only actual keyword matches; zero-score rows are not candidates."""
    if bm25 is None or not chunk_ids or not query_tokens:
        return []

    scores = bm25.get_scores(query_tokens)
    scored = [
        (chunk_ids[index], float(score))
        for index, score in enumerate(scores[: len(chunk_ids)])
        if float(score) > 0.0
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:candidate_k]


def search(query: str, k: int = _cfg.RETRIEVAL_K) -> list[Chunk]:
    """Retrieve relevant chunks using thresholded vector search and positive BM25."""
    if not query.strip() or k <= 0:
        return []

    with _active_state() as (collection, _, bm25, bm25_ids, all_chunks):
        chunk_count = collection.count()
        if chunk_count == 0:
            return []

        candidate_k = min(_cfg.RETRIEVAL_CANDIDATE_K, chunk_count)
        query_embedding = _embed([query])
        results = collection.query(
            query_embeddings=query_embedding,  # type: ignore[arg-type]
            n_results=candidate_k,
            include=["documents", "metadatas", "distances"],
        )

        id_groups = results.get("ids") or []
        if not id_groups or not id_groups[0]:
            return []

        result_ids = id_groups[0]
        distance_groups = results.get("distances") or []
        document_groups = results.get("documents") or []
        metadata_groups = results.get("metadatas") or []
        distances = distance_groups[0] if distance_groups else []
        documents = document_groups[0] if document_groups else []
        metadatas = metadata_groups[0] if metadata_groups else []

        vector_chunks: dict[str, Chunk] = {}
        vector_ranked: list[tuple[str, float]] = []
        for index, chunk_id in enumerate(result_ids):
            if index >= len(distances):
                continue
            distance = float(distances[index])
            if distance > _cfg.MIN_SIMILARITY:
                continue

            text = documents[index] if index < len(documents) else ""
            metadata = metadatas[index] if index < len(metadatas) else {}
            vector_chunks[chunk_id] = Chunk(
                id=chunk_id,
                text=text if isinstance(text, str) else "",
                metadata=metadata if isinstance(metadata, dict) else {},
            )
            vector_ranked.append((chunk_id, distance))

        bm25_ranked = _positive_bm25_results(
            bm25, bm25_ids, _tokenize(query), candidate_k
        )
        fused_ids = _rrf_fusion(vector_ranked, bm25_ranked)
        return [
            vector_chunks[chunk_id]
            if chunk_id in vector_chunks
            else all_chunks[chunk_id]
            for chunk_id in fused_ids[:k]
            if chunk_id in vector_chunks or chunk_id in all_chunks
        ]


def get_index_stats() -> dict[str, object]:
    with _active_state() as (collection, name, bm25, _, _):
        chunk_count = collection.count()
    return {
        "chunk_count": chunk_count,
        "knowledge_base_dir": str(_cfg.KNOWLEDGE_BASE_DIR),
        "has_index": chunk_count > 0,
        "has_bm25": bm25 is not None,
        "active_collection": name,
        "retrieval_k": _cfg.RETRIEVAL_K,
        "candidate_k": _cfg.RETRIEVAL_CANDIDATE_K,
        "min_similarity": _cfg.MIN_SIMILARITY,
    }
