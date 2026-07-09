"""Plain text document loader."""
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def load_text_files(directory: Path) -> list[dict]:
    """
    Load .txt files as-is.
    Returns [{path, content}, ...].
    """
    files = []
    for txt_file in sorted(directory.rglob("*.txt")):
        if any(part.startswith(".") for part in txt_file.parts):
            continue
        try:
            content = txt_file.read_text(encoding="utf-8")
            if content.strip():
                files.append({
                    "path": str(txt_file.relative_to(directory)),
                    "content": content,
                })
        except Exception:
            logger.warning(f"Cannot read {txt_file}, skipping")
    return files
