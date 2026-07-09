"""HTML document loader — extracts readable text from HTML files."""
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def load_html_files(directory: Path) -> list[dict]:
    """
    Load .html/.htm files and extract text content.
    Uses BeautifulSoup to strip tags and extract semantic sections.
    Returns [{path, content}, ...].
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.warning("beautifulsoup4 not installed, skipping HTML files")
        return []

    files = []
    for pattern in ("*.html", "*.htm"):
        for html_file in sorted(directory.rglob(pattern)):
            if any(part.startswith(".") for part in html_file.parts):
                continue
            try:
                soup = BeautifulSoup(html_file.read_text(encoding="utf-8"), "html.parser")

                # Remove non-content elements
                for tag in soup(["script", "style", "nav", "footer", "noscript"]):
                    tag.decompose()

                # Priority: semantic HTML5 sections with headings
                parts = []
                for section_tag in ("article", "section", "main"):
                    for el in soup.find_all(section_tag):
                        text = _extract_section_text(el)
                        if text:
                            parts.append(text)

                # Fallback: extract all headings + paragraphs
                if not parts:
                    text = _extract_heading_paragraph_structure(soup)
                    if text:
                        parts.append(text)

                # Last resort: plain text
                if not parts:
                    body = soup.find("body")
                    text = body.get_text(separator="\n", strip=True) if body else soup.get_text(separator="\n", strip=True)
                    if text:
                        parts.append(text)

                full_text = "\n\n".join(parts)
                if full_text.strip():
                    # Try to extract date from filename
                    rel_path = str(html_file.relative_to(directory))
                    files.append({
                        "path": rel_path,
                        "content": full_text.strip(),
                    })
            except Exception as e:
                logger.warning(f"Cannot parse {html_file}: {e}")
    return files


def _extract_section_text(el) -> str:
    """Extract text from a semantic section, preserving heading hierarchy."""
    lines = []
    for child in el.descendants:
        if child.name in ("h1", "h2", "h3", "h4"):
            lines.append(f"## {child.get_text(strip=True)}")
        elif child.name == "p":
            text = child.get_text(" ", strip=True)
            if text:
                lines.append(text)
        elif child.name == "li":
            text = child.get_text(" ", strip=True)
            if text:
                lines.append(f"- {text}")
    return "\n".join(lines)


def _extract_heading_paragraph_structure(soup) -> str:
    """Fallback: extract all headings and paragraphs in document order."""
    lines = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]):
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        if tag.name.startswith("h"):
            level = int(tag.name[1])
            prefix = "#" * min(level, 3)
            lines.append(f"{prefix} {text}")
        elif tag.name == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
    return "\n".join(lines)
