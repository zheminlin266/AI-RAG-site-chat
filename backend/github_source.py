"""Safely clone a GitHub repository or a folder within one into a local cache."""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

logger = logging.getLogger(__name__)

_GITHUB_TREE_RE = re.compile(
    r"^https?://github\.com/([^/?#]+)/([^/?#]+)/tree/([^?#]+?)/?$",
    re.IGNORECASE,
)
_GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/([^/?#]+)/([^/?#]+)/?$", re.IGNORECASE
)
_REPO_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def is_github_url(raw: str) -> bool:
    """Return whether a value has one of the supported GitHub URL forms."""
    value = raw.strip()
    return bool(_GITHUB_TREE_RE.match(value) or _GITHUB_REPO_RE.match(value))


def _safe_relative_path(raw_path: str) -> str:
    """Validate a URL folder path before passing it to git or the filesystem."""
    value = unquote(raw_path)
    if not value or value.startswith("/") or "\\" in value:
        raise ValueError("GitHub folder path must be a non-empty relative POSIX path")

    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("GitHub folder path must not contain empty, '.' or '..' segments")

    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise ValueError("GitHub folder path must stay inside the repository")
    return path.as_posix()


def _safe_repo_part(value: str, label: str) -> str:
    if not value or value in {".", ".."} or not _REPO_PART_RE.fullmatch(value):
        raise ValueError(f"GitHub {label} contains unsupported characters")
    return value


def parse_github_url(url: str) -> tuple[str, str, str | None, str]:
    """Parse a GitHub URL into ``(owner, repo, branch, path)``.

    ``branch`` is ``None`` for a whole-repository URL. This lets ``git clone``
    use the repository's default branch instead of incorrectly requesting a
    branch literally named ``HEAD``.
    """
    value = url.strip()
    match = _GITHUB_TREE_RE.match(value)
    if match:
        owner, raw_repo, raw_tail = match.groups()
        owner = _safe_repo_part(owner, "owner")
        repo = _safe_repo_part(raw_repo.removesuffix(".git"), "repository")
        parts = unquote(raw_tail).split("/")
        if not parts or parts[0] in {"", ".", ".."}:
            raise ValueError(f"Not a recognized GitHub URL: {url}")
        # This is a syntactic fallback only. clone_or_pull resolves the longest
        # matching remote ref, which handles normal GitHub branches with '/'.
        fallback_path = "/".join(parts[1:])
        return owner, repo, parts[0], _safe_relative_path(fallback_path) if fallback_path else ""

    match = _GITHUB_REPO_RE.match(value)
    if match:
        owner, raw_repo = match.groups()
        owner = _safe_repo_part(owner, "owner")
        repo = _safe_repo_part(raw_repo.removesuffix(".git"), "repository")
        return owner, repo, None, ""

    raise ValueError(f"Not a recognized GitHub URL: {url}")


def _cache_path(
    cache_dir: Path, owner: str, repo: str, branch: str | None, path: str
) -> Path:
    source_key = "\0".join((owner, repo, branch or "<default>", path))
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:16]
    # The hash makes branch and sparse-path changes use independent caches.
    return cache_dir / f"{owner}_{repo}_{digest}"


def _resolved_tree_ref(clone_url: str, raw_url: str) -> tuple[str, str]:
    """Resolve GitHub's ambiguous ``tree/<ref>/<path>`` form via remote refs."""
    match = _GITHUB_TREE_RE.match(raw_url.strip())
    if not match:
        raise ValueError(f"Not a recognized GitHub tree URL: {raw_url}")
    raw_tail = unquote(match.group(3)).strip("/")
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", clone_url],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"Could not resolve GitHub branch from URL: {_command_error(error)}") from error

    refs = [
        line.split("\t", 1)[1][len("refs/heads/") :]
        for line in result.stdout.splitlines()
        if "\trefs/heads/" in line
    ]
    matches = [ref for ref in refs if raw_tail == ref or raw_tail.startswith(ref + "/")]
    if not matches:
        raise ValueError(f"No branch in the GitHub URL matches a remote branch: {raw_url}")
    branch = max(matches, key=len)
    remainder = raw_tail[len(branch) :].lstrip("/")
    return branch, _safe_relative_path(remainder) if remainder else ""


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _target_path(repo_cache: Path, path: str) -> Path:
    root = repo_cache.resolve()
    target = root
    if path:
        target = (root / Path(*PurePosixPath(path).parts)).resolve()
    if not _is_within(target, root):
        raise RuntimeError("GitHub folder path escapes the checked-out repository")
    if not target.exists() or not target.is_dir():
        display_path = path or "/"
        raise RuntimeError(f"Path '{display_path}' was not found in the GitHub repository")
    return target


def _remove_partial_cache(repo_cache: Path, cache_dir: Path) -> None:
    """Remove only a cache entry we created; never recurse outside cache_dir."""
    if not repo_cache.exists() and not repo_cache.is_symlink():
        return
    if repo_cache.is_symlink():
        repo_cache.unlink(missing_ok=True)
        return
    if not _is_within(repo_cache, cache_dir):
        logger.error("Refusing to remove cache outside GITHUB_CACHE_DIR: %s", repo_cache)
        return
    shutil.rmtree(repo_cache, ignore_errors=True)


def _command_error(error: Exception) -> str:
    if isinstance(error, subprocess.CalledProcessError):
        return (error.stderr or error.stdout or str(error)).strip()
    if isinstance(error, subprocess.TimeoutExpired):
        return f"timed out after {error.timeout} seconds"
    return str(error)


def _is_git_repo(repo_cache: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_cache), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return result.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def clone_or_pull(github_url: str, cache_dir: Path) -> Path:
    """Clone or refresh the selected GitHub source and return its safe folder."""
    owner, repo, branch, path = parse_github_url(github_url)
    clone_url = f"https://github.com/{owner}/{repo}.git"

    if not _git_available():
        raise RuntimeError(
            "git is not installed or not on PATH. Install git to use GitHub data sources."
        )

    if _GITHUB_TREE_RE.match(github_url.strip()):
        branch, path = _resolved_tree_ref(clone_url, github_url)

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_root = cache_dir.resolve()
    repo_cache = _cache_path(cache_root, owner, repo, branch, path)

    if repo_cache.exists() or repo_cache.is_symlink():
        if not _is_git_repo(repo_cache):
            logger.warning("Removing incomplete GitHub cache: %s", repo_cache)
            _remove_partial_cache(repo_cache, cache_root)
        else:
            logger.info("Pulling updates for %s/%s...", owner, repo)
            try:
                subprocess.run(
                    ["git", "-C", str(repo_cache), "pull", "--ff-only"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=True,
                )
            except (OSError, subprocess.SubprocessError) as error:
                # A previously complete cache remains usable if the remote is down.
                logger.warning("git pull failed; using cached copy: %s", _command_error(error))
            return _target_path(repo_cache, path)

    logger.info(
        "Cloning %s/%s (branch=%s, path=%s)...",
        owner,
        repo,
        branch or "default",
        path or "/",
    )
    clone_command = ["git", "clone", "--depth", "1", "--filter=blob:none"]
    if path:
        clone_command.append("--sparse")
    if branch:
        clone_command.extend(["--branch", branch])
    clone_command.extend([clone_url, str(repo_cache)])

    try:
        subprocess.run(
            clone_command,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        if path:
            subprocess.run(
                ["git", "-C", str(repo_cache), "sparse-checkout", "set", "--", path],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        return _target_path(repo_cache, path)
    except (OSError, subprocess.SubprocessError) as error:
        _remove_partial_cache(repo_cache, cache_root)
        reason = _command_error(error)
        raise RuntimeError(
            f"Failed to clone {owner}/{repo}: {reason}. "
            "Check that the repository, branch, and folder are public and valid."
        ) from error


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=5, check=True
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
