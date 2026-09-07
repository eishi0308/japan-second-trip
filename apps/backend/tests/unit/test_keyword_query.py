"""Lexical query construction.

Regression guard for the defect the retrieval eval caught: PostgreSQL's
``plainto_tsquery`` ANDs every term, so a natural-language question missing one
word from a document scored **zero against every document in the corpus**.
Lexical search contributed nothing at all on that query class.

The fix ORs the terms. These tests pin that behaviour, and pin the sanitisation
that keeps user text out of ``to_tsquery``'s syntax.
"""

from __future__ import annotations

import pytest

from jst_api.db.repositories.evidence_repo import EvidenceRepository

build = EvidenceRepository._or_tsquery_text


class TestOrSemantics:
    def test_terms_are_ored_not_anded(self):
        """The whole point: a document need not contain every word."""
        assert build("rail pass region") == "rail | pass | region"

    def test_the_query_that_exposed_the_bug(self):
        result = build("should I buy a rail pass for a single region")
        assert " | " in result
        assert "&" not in result
        # "i" and "a" are dropped as single characters; the rest survive.
        assert set(result.split(" | ")) == {
            "should",
            "buy",
            "rail",
            "pass",
            "for",
            "single",
            "region",
        }

    def test_duplicates_are_collapsed_in_order(self):
        assert build("bus bus train bus") == "bus | train"

    def test_single_characters_are_dropped(self):
        assert build("a I of the bus") == "of | the | bus"


class TestSanitisation:
    @pytest.mark.parametrize(
        "hostile",
        [
            "ginzan & (onsen | !bus)",
            "rail <-> pass",
            "onsen:*",
            "'; DROP TABLE evidence_chunks; --",
            "bus & !train",
        ],
    )
    def test_tsquery_operators_never_survive(self, hostile: str):
        """Anything reaching to_tsquery must be plain terms joined by `|`.

        A stray operator would be a syntax error at best and an injection at
        worst, so tokens are reduced to alphanumerics before joining.
        """
        result = build(hostile)
        for operator in ("&", "!", "<->", ":*", "(", ")", "'", ";", "--"):
            assert operator not in result, f"{operator!r} survived in {result!r}"

    def test_empty_and_punctuation_only_queries_yield_nothing(self):
        assert build("") == ""
        assert build("!!! ??? ...") == ""

    def test_japanese_place_names_survive(self):
        """Proper nouns are the reason lexical search exists here."""
        result = build("Ginzan Onsen Oishida Hanagasa Bus")
        assert set(result.split(" | ")) == {"ginzan", "onsen", "oishida", "hanagasa", "bus"}
