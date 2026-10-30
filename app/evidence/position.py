"""Pure position plausibility checks against a plot polygon or pin+acres circle (Step 04)."""

import math
from typing import Any

import shapely
from pyproj import Transformer
from shapely.geometry import Point

from app.evidence.area import SQM_PER_ACRE, parse_valid_polygon

# Project WGS84 (lon, lat) -> UTM Zone 43N (EPSG:32643, metres, covers Punjab)
_TRANSFORMER = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)


def _to_utm(geometry: shapely.Geometry) -> shapely.Geometry:
    """Reproject a Shapely geometry from WGS84 to UTM Zone 43N.

    Uses shapely.transform (Shapely 2.x) instead of the deprecated shapely.ops.transform.
    shapely.transform passes coordinates as an (N, 2) ndarray; we update x/y in-place
    so no explicit numpy import is required beyond what shapely already pulls in.
    """
    def _project(coords):  # coords: ndarray shape (N, 2)
        xs, ys = _TRANSFORMER.transform(coords[:, 0], coords[:, 1])
        out = coords.copy()
        out[:, 0] = xs
        out[:, 1] = ys
        return out

    return shapely.transform(geometry, _project)


def _extract_plot_attr(plot: Any, key: str, default: Any = None) -> Any:
    if plot is None:
        return default
    if isinstance(plot, dict):
        return plot.get(key, default)
    return getattr(plot, key, default)


def check_position(
    lat: float | None,
    lon: float | None,
    accuracy_m: float | None,
    plot: Any,
) -> dict[str, Any]:
    """Check a reported GPS position against a plot (polygon or pin + acres).

    Returns {"distance_to_plot_m": float | None, "plausible": bool | None, "position_state": str}.
    """
    if lat is None or lon is None:
        return {
            "distance_to_plot_m": None,
            "plausible": None,
            "position_state": "not_given",
        }

    geojson = _extract_plot_attr(plot, "geojson")
    pin_lat = _extract_plot_attr(plot, "pin_lat")
    if pin_lat is None:
        pin_lat = _extract_plot_attr(plot, "centroid_lat") or _extract_plot_attr(plot, "lat")
    pin_lon = _extract_plot_attr(plot, "pin_lon")
    if pin_lon is None:
        pin_lon = _extract_plot_attr(plot, "centroid_lon") or _extract_plot_attr(plot, "lon")

    acres = _extract_plot_attr(plot, "acres")
    if acres is None:
        acres_x100 = _extract_plot_attr(plot, "acres_x100")
        if acres_x100 is not None:
            acres = float(acres_x100) / 100.0

    if not geojson and (pin_lat is None or pin_lon is None):
        return {
            "distance_to_plot_m": None,
            "plausible": None,
            "position_state": "not_checked",
        }

    pt_utm = _to_utm(Point(float(lon), float(lat)))
    acc = float(accuracy_m) if accuracy_m is not None else 0.0
    tolerance_m = max(30.0, acc)

    dist_m: float | None = None

    # 1. With a polygon: distance in UTM 43N metres from point to polygon (0 if inside)
    if geojson:
        poly_wgs84 = parse_valid_polygon(geojson)
        poly_utm = _to_utm(poly_wgs84)
        if poly_utm.contains(pt_utm) or poly_utm.touches(pt_utm):
            dist_m = 0.0
        else:
            dist_m = round(float(poly_utm.distance(pt_utm)), 1)
    # 2. With only a pin and acres: circle around the pin with the plot's area
    elif pin_lat is not None and pin_lon is not None:
        pin_utm = _to_utm(Point(float(pin_lon), float(pin_lat)))
        center_dist_m = float(pt_utm.distance(pin_utm))
        plot_acres = float(acres) if (acres is not None and float(acres) > 0) else 0.0
        radius_m = math.sqrt((plot_acres * SQM_PER_ACRE) / math.pi) if plot_acres > 0 else 0.0
        dist_m = 0.0 if center_dist_m <= radius_m else round(center_dist_m - radius_m, 1)

    if dist_m is None:
        return {
            "distance_to_plot_m": None,
            "plausible": None,
            "position_state": "not_checked",
        }

    # E4: accuracy_m over 100 -> plausible is False
    if accuracy_m is not None and float(accuracy_m) > 100.0:
        return {
            "distance_to_plot_m": dist_m,
            "plausible": False,
            "position_state": "mismatch",
        }

    is_plausible = dist_m <= tolerance_m
    return {
        "distance_to_plot_m": dist_m,
        "plausible": is_plausible,
        "position_state": "plausible" if is_plausible else "mismatch",
    }
