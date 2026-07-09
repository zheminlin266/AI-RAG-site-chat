"""
GitHub folder data source — parse GitHub URLs, sparse clone repos into local cache.

Supported URL formats:
  https://github.com/{owner}/{repo}/tree/{branch}/{path}
  https://github.com/{owner}/{repo}  (whole repo, default branch)

ponytail: uses subprocess git, requires git on PATH. Sparse checkout
is depth-1 blobless, so even large repos are fast. Network errors surface
as clear exceptions; no retry logic.
"""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_GITHUB_TREE_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)$"
)
_GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/?$"
)


def is_github_url(raw: str) -> bool:
    """Check if a URL points to a GitHub repo or folder."""
    return bool(_GITHUB_TREE_RE.match(raw) or _GITHUB_REPO_RE.match(raw))


def parse_github_url(url: str) -> tuple[str, str, str, str]:
    """
    Parse a GitHub URL into (owner, repo, branch, path).

    Returns path="" if no subfolder specified.

    Raises ValueError if the URL doesn't match expected patterns.
    """
    m = _GITHUB_TREE_RE.match(url)
    if m:
        return (m.group(1), m.group(2).rstrip(".git"), m.group(3), m.group(4))

    m = _GITHUB_REPO_RE.match(url)
    if m:
        return (m.group(1), m.group(2).rstrip(".git"), "HEAD", "")

    raise ValueError(f"Not a recognized GitHub URL: {url}")


def clone_or_pull(github_url: str, cache_dir: Path) -> Path:
    """
    Clone (or pull) a GitHub repo folder into a local cache.

    Uses sparse checkout for efficiency: only fetches metadata
    and the target folder, not the entire history.

    Returns the Path to the local folder containing the files.
    """
    owner, repo, branch, path = parse_github_url(github_url)
    clone_url = f"https://github.com/{owner}/{repo}.git"
    repo_cache = cache_dir / f"{owner}_{repo}"

    if not _git_available():
        raise RuntimeError(
            "git is not installed or not on PATH. "
            "Install git to use GitHub folder data sources: https://git-scm.com/"
        )

    if repo_cache.exists():
        logger.info(f"Pulling updates for {owner}/{repo}...")
        try:
            subprocess.run(
                ["git", "-C", str(repo_cache), "pull", "--ff-only"],
                capture_output=True, text=True, timeout=60, check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"git pull failed: {e.stderr.strip()}, using cached copy")
        target = repo_cache / path if path else repo_cache
        if target.exists():
            logger.info(f"GitHub source ready: {target}")
            return target
        raise RuntimeError(f"Path '{path}' not found in {owner}/{repo}")

    # Fresh clone
    logger.info(f"Cloning {owner}/{repo} (branch={branch}, path={path or '/'})...")
    try:
        subprocess.run(
            [
                "git", "clone",
                "--depth", "1",
                "--filter=blob:none",
                "--sparse",
                "--branch", branch,
                clone_url,
                str(repo_cache),
            ],
            capture_output=True, text=True, timeout=120, check=True,
        )

        if path:
            subprocess.run(
                ["git", "-C", str(repo_cache), "sparse-checkout", "set", path],
                capture_output=True, text=True, timeout=30, check=True,
            )

        logger.info(f"Clone complete: {repo_cache}")
    except subprocess.CalledProcessError as e:
        # Clean up partial clone
        if repo_cache.exists():
            import shutil
            shutil.rmtree(repo_cache, ignore_errors=True)
        raise RuntimeError(
            f"Failed to clone {owner}/{repo}: {e.stderr.strip()}. "
            "Check that the repo is public and the URL is correct."
        )

    target = repo_cache / path if path else repo_cache
    if not target.exists():
        raise RuntimeError(f"Path '{path}' not found in {owner}/{repo}")
    return target


def _git_available() -> bool:
    """Check if git is available on PATH."""
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True, timeout=5, check=True,
        )
        return True
    except Exception:
        return False
