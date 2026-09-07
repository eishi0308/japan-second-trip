"""Place resolution must not invent a stop.

The existing coverage tested names that are obviously unknown ("Qqxz Imaginary
Village", far below any threshold) and names that match a real alias. Neither
touched the band in between, and that is where the damage was: "Narnia" scored
0.833 against Tokyo's alias "narita", cleared the 0.72 bar, and became a **Tokyo
stop** — silently costed with real shinkansen durations, in a region the
traveller never named.

No threshold can fix that. Measured on this catalogue, "Sendia"→"Sendai" (a typo
that should be accepted) and "Narnia"→"narita" (a different place entirely) both
score 0.833. So the *kind* of match is what decides: name equality and substring
containment are trusted, edit-distance alone is only ever a suggestion.
"""

from __future__ import annotations

import pytest

from travel_mcp.session import TravelMcpSession

pytestmark = pytest.mark.asyncio


class TestMatchKindIsReported:
    @pytest.mark.parametrize(
        ("query", "expected_slug", "expected_kind"),
        [
            ("Ginzan Onsen", "ginzan-onsen", "exact"),
            # matches the catalogue alias "ginzan" exactly, not the display name
            ("ginzan", "ginzan-onsen", "exact"),
            ("Kanazawa city", "kanazawa", "contains"),
            ("Hakata", "fukuoka", "exact"),  # a catalogue alias, matched exactly
        ],
    )
    async def test_trusted_matches_are_labelled_and_resolve(
        self, backend, query, expected_slug, expected_kind
    ):
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call("get_place_details", {"query": query})
        assert result.data["resolved"], query
        assert result.data["place"]["slug"] == expected_slug
        assert result.data["place"]["match_kind"] == expected_kind

    async def test_an_edit_distance_match_is_labelled_fuzzy(self, backend):
        """The tool still reports it — the *caller* decides not to trust it."""
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call("get_place_details", {"query": "Narnia"})
        if result.data["resolved"]:
            assert result.data["place"]["match_kind"] == "fuzzy", (
                "a name that is not in the catalogue must never be labelled exact"
            )


class TestRouteCheckRefusesToGuess:
    """The end-to-end consequence, through the real graph."""

    async def test_a_fuzzy_name_does_not_become_a_stop(self, client, seeded):
        response = await client.post(
            "/api/v1/route-check",
            json={
                "stops": [
                    {"name": "Sendai", "nights": 2},
                    {"name": "Narnia", "nights": 1},
                    {"name": "Ginzan Onsen", "nights": 2},
                ],
                "trip": {"arrival_city": "Tokyo", "driving": "no_car"},
            },
        )
        assert response.status_code == 201
        result = response.json()["result"]

        assert "Narnia" in (result["unresolved_places"] or [])

        # It must not appear as a costed stop under any name — least of all Tokyo.
        costed = (result["parsed_route"] or {}).get("stops", [])
        assert "Narnia" not in [s["raw_name"] for s in costed]
        assert "Tokyo" not in [s["display_name"] for s in costed]

    async def test_the_suggestion_is_offered_not_applied(self, client, seeded):
        """The near miss is shown as a question, in the issue the user reads.

        Unresolved stops are dropped from ``parsed_route``, so a note attached to
        the stop would never reach anyone; the suggestion rides on R23 instead.
        """
        response = await client.post(
            "/api/v1/route-check",
            json={
                "stops": [
                    {"name": "Sendai", "nights": 2},
                    {"name": "Narnia", "nights": 1},
                    {"name": "Ginzan Onsen", "nights": 2},
                ],
                "trip": {"arrival_city": "Tokyo", "driving": "no_car"},
            },
        )
        result = response.json()["result"]
        issues = (result["critical_issues"] or []) + (result["warnings"] or [])
        r23 = next(i for i in issues if i["rule_id"] == "R23_unresolved_stop")
        fix = r23["proposed_fix"] or ""
        assert "did you mean" in fix.lower(), fix
        assert "Narnia" in fix and "Tokyo" in fix, fix

    async def test_the_real_stops_are_still_analysed(self, client, seeded):
        """Refusing one stop must not throw away the rest of the itinerary."""
        response = await client.post(
            "/api/v1/route-check",
            json={
                "stops": [
                    {"name": "Sendai", "nights": 2},
                    {"name": "Narnia", "nights": 1},
                    {"name": "Ginzan Onsen", "nights": 2},
                ],
                "trip": {"arrival_city": "Tokyo", "driving": "no_car"},
            },
        )
        result = response.json()["result"]
        resolved = [
            s["display_name"]
            for s in (result["parsed_route"] or {}).get("stops", [])
            if s["resolved"]
        ]
        assert "Sendai" in resolved and "Ginzan Onsen" in resolved
        assert result["travel_load"], "two resolvable stops is enough to cost the route"

    async def test_an_unresolved_stop_is_reported_as_one(self, client, seeded):
        """R23 used to be mislabelled as a staleness problem."""
        response = await client.post(
            "/api/v1/route-check",
            json={
                "stops": [
                    {"name": "Sendai", "nights": 2},
                    {"name": "Narnia", "nights": 1},
                    {"name": "Ginzan Onsen", "nights": 2},
                ],
                "trip": {"arrival_city": "Tokyo", "driving": "no_car"},
            },
        )
        result = response.json()["result"]
        issues = (result["critical_issues"] or []) + (result["warnings"] or [])
        r23 = next(i for i in issues if i["rule_id"] == "R23_unresolved_stop")
        assert r23["issue_type"] == "unresolved_stop"


class TestNoOverCorrection:
    """The fix must not make ordinary names stop working."""

    @pytest.mark.parametrize(
        ("query", "expected_slug"),
        [("ginzan", "ginzan-onsen"), ("Dogo Onsen", "matsuyama"), ("Hakata", "fukuoka")],
    )
    async def test_aliases_and_substrings_still_resolve(self, backend, query, expected_slug):
        async with TravelMcpSession(backend) as mcp:
            result = await mcp.call("get_place_details", {"query": query})
        assert result.data["resolved"], f"{query} regressed"
        assert result.data["place"]["slug"] == expected_slug
