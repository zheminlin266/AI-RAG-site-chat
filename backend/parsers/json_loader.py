"""JSON document loader — flattens structured data into narrative text."""
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


def load_json_files(directory: Path) -> list[dict]:
    """
    Load .json files and flatten structured arrays into readable text.
    Designed for news digests, data records, and similar structured content.

    Each JSON item is converted to a narrative paragraph preserving
    key fields (date, title, summary, content, source, etc.).
    """
    files = []
    for json_file in sorted(directory.rglob("*.json")):
        # Skip hidden directories and .chroma_db internals
        if any(part.startswith(".") for part in json_file.parts):
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            parts = _flatten_json(data, json_file.name)
            if parts:
                rel_path = str(json_file.relative_to(directory))
                for part in parts:
                    files.append({
                        "path": rel_path,
                        "content": part,
                    })
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON: {json_file}, skipping")
        except Exception as e:
            logger.warning(f"Cannot parse {json_file}: {e}")
    return files


def _flatten_json(data, filename: str) -> list[str]:
    """
    Convert structured JSON into narrative text segments.

    Strategy: detect common patterns:
    - Array of objects with title/content → one segment per item
    - Object with named sections (part1, part2, ...) → one segment per section
    - Flat key-value → one segment for the whole file
    """
    parts = []

    if isinstance(data, list):
        for item in data:
            text = _item_to_text(item)
            if text:
                parts.append(text)
    elif isinstance(data, dict):
        if all(isinstance(v, list) for v in data.values()):
            # Named sections
            for section_name, items in data.items():
                for item in items:
                    text = _item_to_text(item, section=section_name)
                    if text:
                        parts.append(text)
        else:
            text = _dict_to_text(data)
            if text:
                parts.append(text)

    return parts


def _item_to_text(item, section: str = "") -> str:
    """Convert a single JSON item to narrative text."""
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ""

    lines = []
    section_label = f"[{section}] " if section else ""

    # Priority order for key fields
    for key in ("title", "heading", "name"):
        if key in item and item[key]:
            lines.append(f"## {section_label}{item[key]}")
            break
    else:
        if section:
            lines.append(f"## {section_label}")

    if "date" in item:
        lines.append(f"Date: {item['date']}")

    if "summary" in item:
        lines.append(str(item["summary"]))
    elif "content" in item:
        lines.append(str(item["content"]))
    elif "text" in item:
        lines.append(str(item["text"]))

    if "source" in item:
        lines.append(f"Source: {item['source']}")

    if "url" in item:
        lines.append(f"URL: {item['url']}")

    if "tags" in item:
        tags = item["tags"]
        if isinstance(tags, list):
            lines.append(f"Tags: {', '.join(str(t) for t in tags)}")

    # Any remaining key-value pairs as metadata
    skip = {"title", "heading", "name", "date", "summary", "content", "text", "source", "url", "tags"}
    extras = {k: v for k, v in item.items() if k not in skip and not isinstance(v, (list, dict))}
    if extras:
        lines.append(" | ".join(f"{k}: {v}" for k, v in extras.items()))

    return "\n".join(lines)


def _dict_to_text(data: dict) -> str:
    """Convert a flat dict to key-value text."""
    lines = []
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"{key}: {value}")
        elif isinstance(value, list) and all(isinstance(v, str) for v in value):
            lines.append(f"{key}: {', '.join(value)}")
    return "\n".join(lines)
