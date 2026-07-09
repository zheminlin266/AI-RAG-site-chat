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

import hashlib
import logging
from pathlib import Path
from typing import TypedDict

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


def _get_collection() -> chromadb.Collection:
    global _chroma_client, _collection
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=str(_cfg.CHROMA_DB_DIR))
    if _collection is None:
        _collection = _chroma_client.get_or_create_collection(
            name="knowledge",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


# ── BM25 索引（单例） ───────────────────────────────
# ponytail: 全量存储在内存中。O(n) 内存 ≈ chunk 数 × 平均词数。
# 对于 50K 以下 chunk 没问题；超过 100K 建议换用磁盘 BM25（tantivy）。

_bm25_index: BM25Okapi | None = None
_bm25_chunk_ids: list[str] = []  # 与 BM25 索引排序一致的 chunk ID 列表
_all_chunks: dict[str, Chunk] = {}  # chunk_id → Chunk 全量映射（用于 BM25 命中回查）


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


def _get_bm25() -> BM25Okapi | None:
    return _bm25_index


def _get_bm25_chunk_ids() -> list[str]:
    return _bm25_chunk_ids


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


def _rebuild_bm25_from_collection(collection: chromadb.Collection) -> None:
    """
    Rebuild BM25 index from existing ChromaDB collection.
    Called when index exists but BM25 is not built (restart after upgrade).
    """
    global _bm25_index, _bm25_chunk_ids, _all_chunks

    existing = collection.count()
    if existing == 0:
        return

    # Fetch all chunks from ChromaDB in batches
    # ponytail: ChromaDB get() with no filter returns all — fine for <50K chunks
    all_data = collection.get(include=["documents", "metadatas"])
    if not all_data["ids"]:
        return

    ids = all_data["ids"]
    docs = all_data["documents"] or [""] * len(ids)
    metas = all_data["metadatas"] or [{}] * len(ids)

    tokenized = [_tokenize(d) for d in docs]
    _bm25_index = BM25Okapi(tokenized)
    _bm25_chunk_ids = list(ids)
    _all_chunks = {
        cid: Chunk(id=cid, text=t, metadata=m)
        for cid, t, m in zip(ids, docs, metas)
    }
    logger.info(f"BM25 index rebuilt from {len(ids)} existing chunks")


def build_index(force: bool = False) -> int:
    """
    Load all documents, chunk, embed via OpenRouter API, store in ChromaDB.
    Returns total chunk count.
    """
    global _chroma_client, _collection, _bm25_index, _bm25_chunk_ids, _all_chunks

    collection = _get_collection()
    existing = collection.count()
    if existing > 0 and not force:
        # Ensure BM25 is built even if index already exists (restart / upgrade path)
        if _bm25_index is None:
            logger.info(f"Index has {existing} chunks, building BM25 index...")
            _rebuild_bm25_from_collection(collection)
        else:
            logger.info(f"Index has {existing} chunks, skipping rebuild")
        return existing

    if existing > 0:
        logger.info(f"Rebuilding: clearing {existing} existing chunks...")
        _chroma_client.delete_collection("knowledge")
        _collection = None
        _collection = _chroma_client.get_or_create_collection(
            name="knowledge",
            metadata={"hnsw:space": "cosine"},
        )
        collection = _collection

    files = _load_all_documents(_cfg.KNOWLEDGE_BASE_DIR)
    if not files:
        logger.warning(f"No documents found in {_cfg.KNOWLEDGE_BASE_DIR}")
        return 0

    all_chunks: list[Chunk] = []
    for f in files:
        chunks = _split_into_chunks(f["content"], f["path"])
        all_chunks.extend(chunks)

    logger.info(f"Created {len(all_chunks)} chunks from {len(files)} files")
    if not all_chunks:
        return 0

    texts = [c["text"] for c in all_chunks]
    ids = [c["id"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    # 去重：相同内容的 chunk 只保留一份
    seen: set[str] = set()
    dedup_ids, dedup_texts, dedup_metas = [], [], []
    for cid, ct, cm in zip(ids, texts, metadatas):
        if cid not in seen:
            seen.add(cid)
            dedup_ids.append(cid)
            dedup_texts.append(ct)
            dedup_metas.append(cm)

    dup_count = len(texts) - len(dedup_ids)
    if dup_count:
        logger.info(f"Removed {dup_count} duplicate chunks")

    logger.info(f"Generating embeddings for {len(dedup_texts)} chunks via OpenRouter...")
    embeddings = _embed_in_batches(dedup_texts, batch_size=50)

    collection.add(
        ids=dedup_ids,
        embeddings=embeddings,  # type: ignore[arg-type]
        documents=dedup_texts,
        metadatas=dedup_metas,  # type: ignore[arg-type]
    )

    logger.info(f"Index built: {len(dedup_ids)} chunks")

    # ── 同步构建 BM25 索引 ──
    tokenized = [_tokenize(t) for t in dedup_texts]
    _bm25_index = BM25Okapi(tokenized)
    _bm25_chunk_ids = dedup_ids[:]
    _all_chunks = {cid: Chunk(id=cid, text=t, metadata=m)
                   for cid, t, m in zip(dedup_ids, dedup_texts, dedup_metas)}
    logger.info(f"BM25 index built: {len(dedup_ids)} documents")

    return len(dedup_ids)


def search(query: str, k: int = _cfg.RETRIEVAL_K) -> list[Chunk]:
    """
    Hybrid retrieval: vector (semantic) + BM25 (keyword) → RRF fusion.

    1. Vector search → K candidates with cosine distances
    2. BM25 keyword search → K candidates
    3. Distance threshold: drop vector results with distance > MIN_SIMILARITY
    4. RRF merge both ranked lists
    5. Return top-K chunks (or empty list if nothing relevant found)
    """
    candidate_k = _cfg.RETRIEVAL_CANDIDATE_K
    min_sim = _cfg.MIN_SIMILARITY

    # ── Vector search ──
    collection = _get_collection()
    if collection.count() == 0:
        return []

    query_embedding = _embed([query])
    results = collection.query(
        query_embeddings=query_embedding,  # type: ignore[arg-type]
        n_results=candidate_k,
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"] or not results["ids"][0]:
        return []

    vector_chunks: dict[str, Chunk] = {}
    vector_ranked: list[tuple[str, float]] = []  # (chunk_id, distance)

    for i, chunk_id in enumerate(results["ids"][0]):
        dist = results["distances"][0][i] if results["distances"] else 0.0
        text = results["documents"][0][i] if results["documents"] else ""
        meta = results["metadatas"][0][i] if results["metadatas"] else {}

        # Distance threshold: drop irrelevant chunks
        if dist > min_sim:
            continue

        vector_chunks[chunk_id] = Chunk(id=chunk_id, text=text, metadata=meta)
        # Invert distance for RRF ranking (smaller distance = more relevant = lower rank)
        vector_ranked.append((chunk_id, dist))

    # ── BM25 keyword search ──
    bm25 = _get_bm25()
    bm25_ids = _get_bm25_chunk_ids()
    bm25_ranked: list[tuple[str, float]] = []

    if bm25 is not None and bm25_ids:
        tokenized_query = _tokenize(query)
        scores = bm25.get_scores(tokenized_query)

        # Build (chunk_id, score) pairs and sort by score descending
        scored = [(bm25_ids[i], float(scores[i])) for i in range(len(bm25_ids))]
        scored.sort(key=lambda x: x[1], reverse=True)
        bm25_ranked = scored[:candidate_k]

    # ── RRF fusion ──
    fused_ids = _rrf_fusion(vector_ranked, bm25_ranked)

    if not fused_ids:
        return []

    # ── Collect results, preferring vector chunks for text/metadata ──
    result_chunks: list[Chunk] = []
    for cid in fused_ids[:k]:
        if cid in vector_chunks:
            result_chunks.append(vector_chunks[cid])
        elif cid in _all_chunks:
            result_chunks.append(_all_chunks[cid])
        else:
            # Should not happen in normal operation
            logger.warning(f"Chunk {cid} not found in vector_chunks or _all_chunks")

    return result_chunks


def get_index_stats() -> dict:
    collection = _get_collection()
    bm25 = _get_bm25()
    return {
        "chunk_count": collection.count(),
        "knowledge_base_dir": str(_cfg.KNOWLEDGE_BASE_DIR),
        "has_index": collection.count() > 0,
        "has_bm25": bm25 is not None,
        "retrieval_k": _cfg.RETRIEVAL_K,
        "candidate_k": _cfg.RETRIEVAL_CANDIDATE_K,
        "min_similarity": _cfg.MIN_SIMILARITY,
    }
