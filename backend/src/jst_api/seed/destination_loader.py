"""Load the nationwide destination catalogue (hubs, backbone, destinations, fragile links).

Idempotent, and every row is ``is_demo=True``. Called from
``seed.loader.seed_catalogue`` so the app, the tests and the evals all see the
same data.

Every fact gets a source and a date, because the product never shows a fact
without one (PRODUCT_AMENDMENTS.md §2.3). The sources are honest about what
they are: ``demo_seed`` rows with no URL, titled "DEMO", whose notes say the
record was hand-authored and not checked against an operator.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.core.logging import get_logger
from jst_api.db.models import Destination, FragileLink, Hub, HubLink, Place, Source
from jst_api.domain.enums import SourceType, TrustLevel
from jst_api.seed.destinations import DESTINATIONS
from jst_api.seed.fragile import FRAGILE_LINKS
from jst_api.seed.hubs import HUB_LINKS, HUBS

log = get_logger(__name__)

CATALOGUE_SOURCE_TITLE = "DEMO destination catalogue (hand-authored)"
CATALOGUE_VERIFIED_DAYS_AGO = 30

_DEMO_NOTE = (
    "Hand-authored demo record. Plausible, but not checked against an operator "
    "or official source. Shown to travellers with a DEMO label."
)


async def seed_destination_catalogue(
    session: AsyncSession, *, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    counts = {"hubs": 0, "hub_links": 0, "destinations": 0, "fragile_links": 0}

    catalogue_source = await _catalogue_source(session, now)
    catalogue_verified_at = now - timedelta(days=CATALOGUE_VERIFIED_DAYS_AGO)

    existing_hubs = set((await session.scalars(select(Hub.slug))).all())
    for data in HUBS:
        if data["slug"] in existing_hubs:
            continue
        session.add(Hub(**data, is_demo=True))
        counts["hubs"] += 1
    await session.flush()

    existing_links = {
        (f, t, m)
        for f, t, m in (
            await session.execute(select(HubLink.from_hub, HubLink.to_hub, HubLink.mode))
        ).all()
    }
    for link in HUB_LINKS:
        for a, b in ((link["a"], link["b"]), (link["b"], link["a"])):
            if (a, b, link["mode"]) in existing_links:
                continue
            session.add(
                HubLink(
                    from_hub=a,
                    to_hub=b,
                    mode=link["mode"],
                    minutes=link["minutes"],
                    transfers=link["transfers"],
                    note=link["note"],
                    source_id=catalogue_source.id,
                    verified_at=catalogue_verified_at,
                    is_demo=True,
                )
            )
            existing_links.add((a, b, link["mode"]))
            counts["hub_links"] += 1
    await session.flush()

    place_slugs = set((await session.scalars(select(Place.slug))).all())
    fragile_slugs = {row["destination_slug"] for row in FRAGILE_LINKS}
    existing_destinations = set((await session.scalars(select(Destination.slug))).all())
    for data in DESTINATIONS:
        if data["slug"] in existing_destinations:
            continue
        session.add(
            Destination(
                **data,
                place_slug=data["slug"] if data["slug"] in place_slugs else None,
                has_fragile_links=data["slug"] in fragile_slugs,
                source_id=catalogue_source.id,
                verified_at=catalogue_verified_at,
                is_demo=True,
            )
        )
        counts["destinations"] += 1
    await session.flush()

    names = {d["slug"]: d["name"] for d in DESTINATIONS}
    existing_fragile = {
        (d, k, t)
        for d, k, t in (
            await session.execute(
                select(FragileLink.destination_slug, FragileLink.kind, FragileLink.title)
            )
        ).all()
    }
    for row in FRAGILE_LINKS:
        key = (row["destination_slug"], row["kind"], row["title"])
        if key in existing_fragile:
            continue
        days = row["verified_days_ago"]
        verified_at = now - timedelta(days=days) if days is not None else None
        source = Source(
            title=f"DEMO record: {names[row['destination_slug']]}: {row['title']}",
            source_type=SourceType.DEMO_SEED.value,
            official_source=False,
            trust_level=(TrustLevel.SECONDARY if verified_at else TrustLevel.UNVERIFIED).value,
            place_slug=row["destination_slug"],
            language="en",
            fetched_at=verified_at,
            verified_at=verified_at,
            verified_by="seed" if verified_at else None,
            freshness_ttl_days=row["ttl_days"],
            status="active",
            is_demo=True,
            notes=_DEMO_NOTE,
        )
        session.add(source)
        await session.flush()
        session.add(
            FragileLink(
                destination_slug=row["destination_slug"],
                kind=row["kind"],
                severity=row["severity"],
                title=row["title"],
                detail=row["detail"],
                last_departure_local=row["last_departure_local"],
                closed_months=row["closed_months"],
                closed_weekdays=row["closed_weekdays"],
                lead_time_days=row["lead_time_days"],
                frequency_per_day=row["frequency_per_day"],
                status=row["status"] if verified_at else "unverified",
                conflicting_values=row["conflicting_values"],
                source_id=source.id,
                verified_at=verified_at,
                freshness_ttl_days=row["ttl_days"],
                is_demo=True,
            )
        )
        counts["fragile_links"] += 1
    await session.flush()

    log.info("seed.destination_catalogue", **counts)
    return counts


async def _catalogue_source(session: AsyncSession, now: datetime) -> Source:
    source = await session.scalar(select(Source).where(Source.title == CATALOGUE_SOURCE_TITLE))
    if source is not None:
        return source
    verified_at = now - timedelta(days=CATALOGUE_VERIFIED_DAYS_AGO)
    source = Source(
        title=CATALOGUE_SOURCE_TITLE,
        source_type=SourceType.DEMO_SEED.value,
        official_source=False,
        trust_level=TrustLevel.SECONDARY.value,
        language="en",
        fetched_at=verified_at,
        verified_at=verified_at,
        verified_by="seed",
        freshness_ttl_days=365,
        status="active",
        is_demo=True,
        notes=(
            "Hub times, destination attributes and season fit, hand-authored as "
            "editorial approximations. Not a timetable."
        ),
    )
    session.add(source)
    await session.flush()
    return source
