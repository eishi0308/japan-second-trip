"""Load the destination catalogue into the planner's value types.

Read once per request (a few hundred rows). The planner itself does no I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.db.models import Destination, FragileLink, Hub
from jst_api.db.repositories.catalogue_repo import load_backbone
from jst_api.domain.fact_state import fact_state
from jst_api.planner.model import Catalogue, FragileNote, HubInfo, Place


async def load_planner_catalogue(
    session: AsyncSession, *, now: datetime | None = None
) -> Catalogue:
    now = now or datetime.now(UTC)
    backbone = await load_backbone(session)
    hubs = {
        h.slug: HubInfo(h.slug, h.name, h.area, h.is_international_gateway)
        for h in (await session.scalars(select(Hub))).all()
    }
    notes: dict[str, list[FragileNote]] = {}
    for link in (
        await session.scalars(
            select(FragileLink).order_by(FragileLink.destination_slug, FragileLink.kind)
        )
    ).all():
        notes.setdefault(link.destination_slug, []).append(
            FragileNote(
                kind=link.kind,
                severity=link.severity,
                title=link.title,
                detail=link.detail,
                state=fact_state(link.status, link.verified_at, link.freshness_ttl_days, now=now),
                verified_at=link.verified_at,
                source_id=link.source_id,
                closed_months=tuple(link.closed_months or ()),
                lead_time_days=link.lead_time_days,
                last_departure_local=link.last_departure_local,
                closed_weekdays=tuple(link.closed_weekdays or ()),
                frequency_per_day=link.frequency_per_day,
                conflicting_values=tuple(str(v) for v in link.conflicting_values or ()),
            )
        )
    places = {
        d.slug: Place(
            slug=d.slug,
            name=d.name,
            area=d.area,
            prefecture=d.prefecture,
            hub_slug=d.hub_slug,
            hub_minutes=d.hub_minutes,
            hub_transfers=d.hub_transfers,
            access_mode=d.access_mode,
            car_need=d.car_need,
            season_fit=tuple(d.season_fit),
            themes=tuple(d.themes),
            tier=d.popularity_tier,
            typical_nights=d.typical_nights,
            summary=d.summary,
            verified_at=d.verified_at,
            is_demo=d.is_demo,
            fragile=tuple(notes.get(d.slug, ())),
            source_id=d.source_id,
        )
        for d in (await session.scalars(select(Destination).order_by(Destination.slug))).all()
    }
    return Catalogue(places=places, hubs=hubs, backbone=backbone)
