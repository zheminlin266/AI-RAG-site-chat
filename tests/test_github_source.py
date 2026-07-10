from __future__ import annotations

import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from backend import github_source
from backend.github_source import parse_github_url


class GitHubUrlTests(unittest.TestCase):
    def test_repo_name_is_not_trimmed_like_a_character_set(self) -> None:
        self.assertEqual(
            parse_github_url("https://github.com/example/audit"),
            ("example", "audit", None, ""),
        )

    def test_whole_repository_uses_default_branch(self) -> None:
        _, _, branch, path = parse_github_url("https://github.com/example/repository.git")
        self.assertIsNone(branch)
        self.assertEqual(path, "")

    def test_folder_path_cannot_escape_repository(self) -> None:
        with self.assertRaises(ValueError):
            parse_github_url("https://github.com/example/repo/tree/main/docs/%2E%2E/secrets")

    def test_tree_url_resolves_a_branch_with_a_slash(self) -> None:
        completed = CompletedProcess(
            args=[],
            returncode=0,
            stdout="abc\trefs/heads/main\ndef\trefs/heads/feature/foo\n",
            stderr="",
        )
        with patch.object(github_source.subprocess, "run", return_value=completed):
            self.assertEqual(
                github_source._resolved_tree_ref(
                    "https://github.com/example/repo.git",
                    "https://github.com/example/repo/tree/feature/foo/docs",
                ),
                ("feature/foo", "docs"),
            )
