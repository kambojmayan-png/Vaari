"""Polygon geodesic area (in acres) and centroid calculation (Step 04).

Pure functions: no database, no clock, no side effects.
"""

import json
from typing import Any

from pyproj import Geod
from shapely.geometry import MultiPolygon, Polygon, shape

_GEOD = Geod(ellps="WGS84")
SQM_PER_ACRE = 4046.8564224


def parse_valid_polygon(geojson: str | dict[str, Any]) -> Polygon | MultiPolygon:
    """Parse a GeoJSON string or dict into a validated shapely Polygon/MultiPolygon.

    Raises ValueError on invalid, empty, or self-intersecting polygons.
    """
    if isinstance(geojson, str):
        try:
            data = json.loads(geojson)
        except Exception as exc:
            raise ValueError(f"Invalid GeoJSON string: {exc}") from exc
    elif isinstance(geojson, dict):
        data = geojson
    else:
        raise ValueError("GeoJSON must be a JSON string or dict.")

    if data.get("type") == "FeatureCollection":
        features = data.get("features") or []
        if not features:
            raise ValueError("GeoJSON FeatureCollection is empty.")
        geom_data = features[0].get("geometry")
    elif data.get("type") == "Feature":
        geom_data = data.get("geometry")
    else:
        geom_data = data

    if not isinstance(geom_data, dict) or "type" not in geom_data:
        raise ValueError("GeoJSON missing valid geometry object.")

    geom = shape(geom_data)
    if geom.is_empty:
        raise ValueError("Polygon geometry is empty.")
    if not geom.is_valid:
        raise ValueError("Polygon geometry is invalid or self-intersecting.")
    if not isinstance(geom, (Polygon, MultiPolygon)):
        raise ValueError(f"Expected Polygon or MultiPolygon, got {geom.geom_type}.")

    # Ensure exterior ring has non-zero area
    if geom.area <= 0:
        raise ValueError("Polygon has zero area.")

    return geom


def acres_of_polygon(geojson: str | dict[str, Any]) -> float:
    """Compute geodesic area in acres using WGS84 ellipsoid (1 acre = 4046.8564224 m²)."""
    geom = parse_valid_polygon(geojson)
    area_m2, _ = _GEOD.geometry_area_perimeter(geom)
    acres = abs(area_m2) / SQM_PER_ACRE
    if acres <= 0:
        raise ValueError("Computed polygon area must be positive.")
    return round(acres, 2)


def centroid_of_polygon(geojson: str | dict[str, Any]) -> tuple[float, float]:
    """Return (centroid_lat, centroid_lon) for a valid GeoJSON polygon."""
    geom = parse_valid_polygon(geojson)
    c = geom.centroid
    return round(float(c.y), 6), round(float(c.x), 6)
