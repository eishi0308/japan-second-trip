"""Great-circle geometry and route-shape maths.

Pure functions, no I/O — these are used both by the deterministic rules engine
and by the eval harness, so they must stay side-effect free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class LatLon:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not -90 <= self.lat <= 90:
            raise ValueError(f"latitude out of range: {self.lat}")
        if not -180 <= self.lon <= 180:
            raise ValueError(f"longitude out of range: {self.lon}")


def haversine_km(a: LatLon, b: LatLon) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def path_length_km(points: list[LatLon]) -> float:
    return sum(haversine_km(points[i], points[i + 1]) for i in range(len(points) - 1))


def detour_ratio(points: list[LatLon]) -> float:
    """Total path length divided by the straight-line start→end distance.

    1.0 is a perfectly direct line. Values above ~1.6 mean the itinerary doubles
    back on itself, which is the geometric signature of a backtracking route.
    A closed loop (start == end) returns 1.0 by convention because a loop is a
    legitimate shape, not a detour.
    """
    if len(points) < 3:
        return 1.0
    direct = haversine_km(points[0], points[-1])
    total = path_length_km(points)
    if direct < 25.0:  # effectively a loop back to the origin
        return 1.0
    return total / direct
