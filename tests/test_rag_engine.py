from __future__ import annotations

from contextlib import contextmanager
import unittest
from unittest.mock import patch

try:
    from backend import rag_engine
except ModuleNotFoundError:  # Allows stdlib-only checks before optional deps are installed.
    rag_engine = None


class FakeBM25:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.queries: list[list[str]] = []

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        self.queries.append(query_tokens)
        return self.scores


@unittest.skipIf(rag_engine is None, "RAG dependencies are not installed")
class HybridRetrievalTests(unittest.TestCase):
    def test_bm25_excludes_zero_score_rows_and_empty_tokens(self) -> None:
        bm25 = FakeBM25([0.0, 2.0, 0.0])
        self.assertEqual(
            rag_engine._positive_bm25_results(bm25, ["a", "b", "c"], ["match"], 10),
            [("b", 2.0)],
        )
        self.assertEqual(
            rag_engine._positive_bm25_results(bm25, ["a", "b", "c"], [], 10),
            [],
        )
        self.assertEqual(len(bm25.queries), 1)

    def test_irrelevant_vector_results_and_zero_bm25_return_no_chunks(self) -> None:
        class Collection:
            def count(self) -> int:
                return 2

            def query(self, **_: object) -> dict:
                return {
                    "ids": [["a", "b"]],
                    "distances": [[0.9, 0.8]],
                    "documents": [["first", "second"]],
                    "metadatas": [[{}, {}]],
                }

        @contextmanager
        def active_state():
            yield Collection(), "knowledge", FakeBM25([0.0, 0.0]), ["a", "b"], {}

        with (
            patch.object(rag_engine, "_active_state", active_state),
            patch.object(rag_engine, "_embed", return_value=[[0.1, 0.2]]),
        ):
            self.assertEqual(rag_engine.search("unrelated"), [])
