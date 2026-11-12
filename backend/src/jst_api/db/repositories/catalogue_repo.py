"""Read access to the destination catalogue (hubs, backbone, destinations, fragile links).

SQL only. Turning rows into decisions is the domain layer's job
(``domain/backbone.py``, ``domain/fact_state.py``).
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from jst_api.db.models import Destination, FragileLink, Hub, HubLink
from jst_api.domain.backbone import Backbone, DestinationAccess, Leg


async def load_backbone(session: AsyncSession) -> Backbone:
    rows = (await session.scalars(select(HubLink))).all()
    return Backbone(
        [
            Leg(
                from_hub=row.from_hub,
                to_hub=row.to_hub,
                mode=row.mode,
                minutes=row.minutes,
                transfers=row.transfers,
            )
            for row in rows
        ]
    )


async def list_hubs(session: AsyncSession, *, gateways_only: bool = False) -> list[Hub]:
    stmt = select(Hub).order_by(Hub.slug)
    if gateways_only:
        stmt = stmt.where(Hub.is_international_gateway.is_(True))
    return list((await session.scalars(stmt)).all())


async def list_destinations(
    session: AsyncSession,
    *,
    areas: Collection[str] | None = None,
    car_needs: Collection[str] | None = None,
    slugs: Collection[str] | None = None,
) -> list[Destination]:
    stmt = select(Destination).order_by(Destination.slug)
    if areas is not None:
        stmt = stmt.where(Destination.area.in_(list(areas)))
    if car_needs is not None:
        stmt = stmt.where(Destination.car_need.in_(list(car_needs)))
    if slugs is not None:
        stmt = stmt.where(Destination.slug.in_(list(slugs)))
    return list((await session.scalars(stmt)).all())


async def fragile_links_for(
    session: AsyncSession, destination_slugs: Collection[str]
) -> dict[str, list[FragileLink]]:
    rows = (
        await session.scalars(
            select(FragileLink)
            .where(FragileLink.destination_slug.in_(list(destination_slugs)))
            .order_by(FragileLink.destination_slug, FragileLink.kind)
        )
    ).all()
    grouped: dict[str, list[FragileLink]] = {}
    for row in rows:
        grouped.setdefault(row.destination_slug, []).append(row)
    return grouped


def access_of(destination: Destination) -> DestinationAccess:
    return DestinationAccess(
        slug=destination.slug,
        hub_slug=destination.hub_slug,
        hub_minutes=destination.hub_minutes,
        hub_transfers=destination.hub_transfers,
        access_mode=destination.access_mode,
    )
