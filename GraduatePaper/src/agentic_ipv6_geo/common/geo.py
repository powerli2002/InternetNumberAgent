from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def haversine_km(a: Point, b: Point) -> float:
    lat1 = math.radians(a.lat)
    lon1 = math.radians(a.lon)
    lat2 = math.radians(b.lat)
    lon2 = math.radians(b.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def mean_point(points: Iterable[Point]) -> Point | None:
    points = list(points)
    if not points:
        return None
    return Point(sum(p.lat for p in points) / len(points), sum(p.lon for p in points) / len(points))


def weighted_mean_point(items: Iterable[tuple[Point, float]]) -> Point | None:
    pairs = [(point, weight) for point, weight in items if weight > 0]
    total = sum(weight for _, weight in pairs)
    if total <= 0:
        return None
    return Point(
        lat=sum(point.lat * weight for point, weight in pairs) / total,
        lon=sum(point.lon * weight for point, weight in pairs) / total,
    )


def confidence_from_error_scale(error_km: float, scale_km: float) -> float:
    if scale_km <= 0:
        return 0.0
    return clamp(1.0 - error_km / scale_km)
