"""
RAG 引擎 — 多格式文档加载、分块、向量化、检索。

数据流:
  knowledge-base/*.{md,html,json,txt} → Chunks → Embeddings → ChromaDB
  用户 query → Embedding → ChromaDB.search → Top-K Chunks

支持格式: Markdown、HTML、JSON、纯文本
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TypedDict

import chromadb
from sentence_transformers import SentenceTransformer

import backend.config as _cfg

# 延迟取值：knowledge base dir 可能在运行时被 server.py 的 lifespan 覆盖
# (e.g. GitHub URL → sparse clone → 替换路径)
# 因此不能 from backend.config import KNOWLEDGE_BASE_DIR 做本地拷贝
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


# ── 嵌入模型（单例） ────────────────────────────────

_embedding_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info(f"Loading embedding model: {_cfg.EMBEDDING_MODEL}")
        _embedding_model = SentenceTransformer(_cfg.EMBEDDING_MODEL)
        logger.info(
            f"Model loaded: dim={_embedding_model.get_sentence_embedding_dimension()}"
        )
    return _embedding_model


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


# ── 多格式文档加载 ──────────────────────────────────


def _load_all_documents(directory: Path) -> list[dict]:
    """
    Load all supported document types from a directory.
    Dispatches to format-specific parsers.
    """
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
    """
    Split text into chunks by headings, then sentences for long sections.

    ponytail: simple char-based token estimation instead of tiktoken.
    English ~4 char/token, Chinese ~1.5 char/token.
    Accurate enough for chunk sizing at knowledge-base scale.
    """
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
    """Split text by ## / # headings."""
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
    """Split long sections by sentences with overlap."""
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
    raw = f"{source}|{heading}|{text[:200]}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


# ── 公共 API ────────────────────────────────────────


def build_index(force: bool = False) -> int:
    """
    Load all documents, chunk, embed, store in ChromaDB.
    Returns total chunk count.
    Skips if index exists and force=False.
    """
    collection = _get_collection()
    existing = collection.count()
    if existing > 0 and not force:
        logger.info(f"Index has {existing} chunks, skipping rebuild")
        return existing

    if existing > 0:
        logger.info(f"Rebuilding: clearing {existing} existing chunks...")
        global _chroma_client, _collection
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

    model = get_embedding_model()
    texts = [c["text"] for c in all_chunks]
    ids = [c["id"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]

    logger.info(f"Generating embeddings for {len(texts)} chunks...")
    embeddings = model.encode(texts, show_progress_bar=False).tolist()

    collection.add(
        ids=ids,
        embeddings=embeddings,  # type: ignore[arg-type]
        documents=texts,
        metadatas=metadatas,  # type: ignore[arg-type]
    )

    logger.info(f"Index built: {len(all_chunks)} chunks")
    return len(all_chunks)


def search(query: str, k: int = _cfg.RETRIEVAL_K) -> list[Chunk]:
    """Retrieve top-K relevant chunks for a query."""
    collection = _get_collection()
    if collection.count() == 0:
        return []

    model = get_embedding_model()
    query_embedding = model.encode([query], show_progress_bar=False).tolist()

    results = collection.query(
        query_embeddings=query_embedding,  # type: ignore[arg-type]
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[Chunk] = []
    if results["ids"] and results["ids"][0]:
        for i, chunk_id in enumerate(results["ids"][0]):
            chunks.append(Chunk(
                id=chunk_id,
                text=results["documents"][0][i] if results["documents"] else "",
                metadata=results["metadatas"][0][i] if results["metadatas"] else {},
            ))

    return chunks


def get_index_stats() -> dict:
    collection = _get_collection()
    return {
        "chunk_count": collection.count(),
        "knowledge_base_dir": str(_cfg.KNOWLEDGE_BASE_DIR),
        "has_index": collection.count() > 0,
    }
