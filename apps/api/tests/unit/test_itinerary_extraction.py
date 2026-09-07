"""Free-text itinerary extraction (demo provider).

RouteCheck's headline input path is a paragraph a traveller pasted in. The demo
provider is what makes that path work with no credentials, so its parsing is a
product surface, not a stub.

These tests exist because three of the five most natural phrasings extracted
**zero stops**: the original pattern only understood a night count written
*after* the place ("Ginzan Onsen 2 nights"), so "2 nights Ginzan Onsen" and
"Day 1-2 Sendai" were dropped silently. Fewer than two resolvable stops means no
transport analysis at all, so the whole critique degraded to nothing while still
reporting success.
"""

from __future__ import annotations

import pytest

from jst_api.domain.results import ExtractedItinerary
from jst_api.providers.llm import _demo_extracted_itinerary


def extract(text: str) -> ExtractedItinerary:
    result = _demo_extracted_itinerary({"raw_text": text}, ExtractedItinerary)
    assert isinstance(result, ExtractedItinerary)
    return result


def stops(text: str) -> list[tuple[str, int]]:
    return [(s.name, s.nights) for s in extract(text).stops]


class TestNightCountBeforeThePlace:
    """The phrasing that used to yield nothing at all."""

    def test_nights_first(self):
        assert stops("3 nights Kanazawa then 2 nights Takayama") == [
            ("Kanazawa", 3),
            ("Takayama", 2),
        ]

    def test_abbreviated_nights_first(self):
        assert stops("2N Kanazawa, 1N Shirakawa-go") == [("Kanazawa", 2), ("Shirakawa-go", 1)]

    def test_with_a_preposition(self):
        assert stops("2 nights at Yufuin") == [("Yufuin", 2)]

    def test_nights_after_the_place_still_works(self):
        """The form that already worked must not regress."""
        assert stops("Ginzan Onsen 2 nights, Kanazawa 3 nights") == [
            ("Ginzan Onsen", 2),
            ("Kanazawa", 3),
        ]


class TestDayRanges:
    def test_a_day_range_becomes_a_night_count(self):
        assert stops("Day 1-2 Sendai") == [("Sendai", 2)]

    def test_a_written_range(self):
        assert stops("Days 1 to 3 in Kyushu") == [("Kyushu", 3)]

    def test_a_single_day(self):
        assert stops("Day 5 Tokyo") == [("Tokyo", 1)]

    def test_a_full_day_by_day_itinerary(self):
        assert stops("Day 1 Tokyo, Day 2-4 Hakone, Day 5 Tokyo") == [
            ("Tokyo", 1),
            ("Hakone", 3),
            ("Tokyo", 1),
        ]

    def test_the_inference_is_disclosed_not_hidden(self):
        """Days are not nights. Converting is a guess, so it must be stated."""
        result = extract("Day 1-2 Sendai")
        assert any("days, not nights" in a and "Sendai" in a for a in result.ambiguities), (
            result.ambiguities
        )

    def test_the_note_names_the_cleaned_place(self):
        """The note quotes the user's own words, then names the resolved place.

        It used to end "at in Kyushu" — the connective was stripped from the
        stop but not from the sentence explaining it.
        """
        note = next(a for a in extract("Days 1 to 3 in Kyushu").ambiguities if "days" in a)
        assert note.startswith("'Days 1 to 3 in Kyushu'"), note
        assert note.endswith("at Kyushu."), note


class TestNonPlaces:
    def test_fly_home_is_not_a_stop(self):
        """It reads as a destination but is not somewhere that can be costed.

        Keeping it produced a phantom stop that failed catalogue resolution and
        dragged the itinerary below the two-stop floor for transport analysis.
        """
        assert stops("fly home") == []

    def test_a_real_airport_survives(self):
        assert stops("Narita Airport then 2 nights Tokyo") == [
            ("Narita Airport", 0),
            ("Tokyo", 2),
        ]

    def test_no_phantom_note_for_a_dropped_non_place(self):
        result = extract("2 nights Sendai and fly home")
        assert [s.name for s in result.stops] == ["Sendai"]
        assert not any("home" in a for a in result.ambiguities)


class TestTheRegressionCase:
    """The exact text that exposed the bug end to end."""

    TEXT = "Day 1-2 Sendai, then 2 nights Ginzan Onsen, then back to Sendai and fly home"

    def test_all_three_real_stops_are_recovered(self):
        assert stops(self.TEXT) == [("Sendai", 2), ("Ginzan Onsen", 2), ("Sendai", 0)]

    def test_enough_stops_for_a_transport_analysis(self):
        """Two resolvable stops is the floor below which nothing can be checked."""
        assert len(stops(self.TEXT)) >= 2

    def test_the_return_leg_is_kept(self):
        """A trip that ends where it started names the place twice on purpose."""
        names = [n for n, _ in stops(self.TEXT)]
        assert names[0] == names[-1] == "Sendai"


class TestOrdinaryCases:
    def test_bare_place_names(self):
        assert stops("Kanazawa, Takayama, Shirakawa-go") == [
            ("Kanazawa", 0),
            ("Takayama", 0),
            ("Shirakawa-go", 0),
        ]

    def test_a_missing_night_count_is_disclosed(self):
        assert any("No night count" in a for a in extract("Kanazawa").ambiguities)

    @pytest.mark.parametrize("text", ["", "   ", "!!!", "..."])
    def test_junk_yields_no_stops_rather_than_junk_stops(self, text: str):
        assert stops(text) == []

    def test_consecutive_duplicates_collapse(self):
        assert stops("2 nights Sendai, Sendai") == [("Sendai", 2)]

    def test_night_counts_are_clamped(self):
        assert stops("99 nights Sendai") == [("Sendai", 30)]
