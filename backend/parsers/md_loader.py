"""Markdown document loader."""
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def load_markdown_files(directory: Path) -> list[dict]:
    """
    Recursively load all .md files from a directory.
    Returns [{path, content}, ...].
    """
    files = []
    for md_file in sorted(directory.rglob("*.md")):
        if any(part.startswith(".") for part in md_file.parts):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            if content.strip():
                files.append({
                    "path": str(md_file.relative_to(directory)),
                    "content": content,
                })
        except Exception:
            logger.warning(f"Cannot read {md_file}, skipping")
    return files
