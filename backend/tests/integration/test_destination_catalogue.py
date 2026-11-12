"""M1: the seeded destination catalogue is complete, labelled DEMO and usable.

These run against the real seeded database, the same data the app and the
evals use. They check the product rules in PRODUCT_AMENDMENTS.md §6 and that
the hero demo (§10) has data to work with.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from jst_api.db.models import Destination, FragileLink, Hub, HubLink, Place, Source
from jst_api.db.repositories.catalogue_repo import (
    access_of,
    fragile_links_for,
    list_destinations,
    list_hubs,
    load_backbone,
)
from jst_api.domain.enums import Area, CarNeed, FragileKind, Interest, PopularityTier
from jst_api.domain.fact_state import FactState, fact_state
from jst_api.seed.destination_loader import seed_destination_catalogue
from jst_api.seed.evidence import KNOWN_CONFLICTS

pytestmark = pytest.mark.asyncio(loop_scope="session")

GOLDEN_ROUTE = {"tokyo", "kyoto", "osaka"}
INTERESTS = {i.value for i in Interest}


async def test_catalogue_size_matches_the_product_rule(session) -> None:
    count = await session.scalar(select(func.count()).select_from(Destination))
    assert 100 <= count <= 200


async def test_the_golden_route_is_not_a_destination(session) -> None:
    slugs = set((await session.scalars(select(Destination.slug))).all())
    assert not slugs & GOLDEN_ROUTE


async def test_every_area_is_covered_with_all_three_tiers(session) -> None:
    rows = (await session.execute(select(Destination.area, Destination.popularity_tier))).all()
    assert {area for area, _ in rows} == {a.value for a in Area}
    assert {tier for _, tier in rows} == {t.value for t in PopularityTier}


async def test_every_row_is_demo_and_dated(session) -> None:
    for model in (Hub, HubLink, Destination, FragileLink):
        rows = (await session.scalars(select(model))).all()
        assert rows, model.__tablename__
        assert all(row.is_demo for row in rows), model.__tablename__
    for model in (HubLink, Destination):
        assert all(
            row.source_id and row.verified_at
            for row in (await session.scalars(select(model))).all()
        )


async def test_destination_attributes_are_well_formed(session) -> None:
    for d in await list_destinations(session):
        assert len(d.season_fit) == 12 and all(v in (0, 1, 2, 3) for v in d.season_fit), d.slug
        assert d.themes and set(d.themes) <= INTERESTS, d.slug
        assert d.car_need in {c.value for c in CarNeed}, d.slug
        assert 24.0 <= d.lat <= 45.6 and 122.9 <= d.lon <= 146.0, d.slug
        assert d.hub_minutes >= 0 and d.typical_nights >= 1, d.slug


async def test_every_destination_is_reachable_from_every_gateway(session) -> None:
    backbone = await load_backbone(session)
    gateways = await list_hubs(session, gateways_only=True)
    assert {"tokyo", "osaka", "fukuoka", "sapporo"} <= {h.slug for h in gateways}
    for d in await list_destinations(session):
        for hub in gateways:
            assert backbone.access(hub.slug, access_of(d)) is not None, (hub.slug, d.slug)


async def test_backbone_links_run_both_ways(session) -> None:
    links = {(r.from_hub, r.to_hub, r.mode) for r in (await session.scalars(select(HubLink))).all()}
    assert all((b, a, m) in links for a, b, m in links)


async def test_existing_places_are_linked(session) -> None:
    place_slugs = set((await session.scalars(select(Place.slug))).all())
    linked = (
        await session.scalars(select(Destination).where(Destination.place_slug.is_not(None)))
    ).all()
    assert {"ginzan-onsen", "naoshima", "kamikochi"} <= {d.slug for d in linked}
    assert all(d.place_slug in place_slugs for d in linked)


async def test_around_thirty_fragile_destinations(session) -> None:
    flagged = (
        await session.scalars(select(Destination).where(Destination.has_fragile_links.is_(True)))
    ).all()
    assert 25 <= len(flagged) <= 40
    grouped = await fragile_links_for(session, [d.slug for d in flagged])
    assert set(grouped) == {d.slug for d in flagged}
    kinds = {link.kind for links in grouped.values() for link in links}
    assert kinds == {k.value for k in FragileKind}


async def test_every_fragile_link_has_a_demo_source(session) -> None:
    for link in (await session.scalars(select(FragileLink))).all():
        source = await session.get(Source, link.source_id)
        assert source is not None and source.is_demo
        assert source.title.startswith("DEMO") and source.url is None


async def test_fragile_links_cover_every_display_state(session) -> None:
    now = datetime.now(UTC)
    states = {
        fact_state(link.status, link.verified_at, link.freshness_ttl_days, now=now)
        for link in (await session.scalars(select(FragileLink))).all()
    }
    assert states == set(FactState)


async def test_ginzan_conflict_matches_the_seeded_review(session) -> None:
    link = await session.scalar(
        select(FragileLink).where(
            FragileLink.destination_slug == "ginzan-onsen",
            FragileLink.kind == FragileKind.LAST_CONNECTION.value,
        )
    )
    assert link is not None
    assert link.status == "conflicting"
    assert link.last_departure_local is None
    conflict = next(c for c in KNOWN_CONFLICTS if c["subject"].startswith("ginzan-onsen"))
    assert set(conflict["values"]) <= set(link.conflicting_values)


async def test_hero_demo_has_enough_january_onsen_and_snow_without_a_car(session) -> None:
    """Australian couple, January, Tokyo in/out, 4 nights, no car, onsen + snow + food."""
    backbone = await load_backbone(session)
    candidates = []
    for d in await list_destinations(session, car_needs=["none", "helpful"]):
        access = backbone.access("tokyo", access_of(d))
        assert access is not None
        if d.season_fit[0] >= 2 and {"onsen", "snow"} & set(d.themes) and access.minutes <= 330:
            candidates.append(d)
    assert len(candidates) >= 12
    assert len({d.area for d in candidates}) >= 3
    assert any(d.has_fragile_links for d in candidates)
    assert {"nyuto-onsen", "ginzan-onsen"} <= {d.slug for d in candidates}


async def test_kyushu_is_far_from_tokyo_and_close_to_fukuoka(session) -> None:
    """The data behind the hero demo's "Not for this trip — unless you fly out of Fukuoka"."""
    backbone = await load_backbone(session)
    kurokawa = (await list_destinations(session, slugs=["kurokawa-onsen"]))[0]
    from_tokyo = backbone.access("tokyo", access_of(kurokawa))
    from_fukuoka = backbone.access("fukuoka", access_of(kurokawa))
    assert from_tokyo is not None and from_fukuoka is not None
    assert from_tokyo.minutes >= 2 * from_fukuoka.minutes


async def test_seeding_again_adds_nothing(session) -> None:
    counts = await seed_destination_catalogue(session)
    await session.rollback()
    assert counts == {"hubs": 0, "hub_links": 0, "destinations": 0, "fragile_links": 0}
