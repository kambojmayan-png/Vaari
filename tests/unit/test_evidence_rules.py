"""Unit tests for Step 04: pure evidence rules, position checks (E1-E8), and polygon geodesic area."""

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

import pytest
import shapely
from pyproj import Transformer
from shapely.geometry import box

from app.evidence.area import SQM_PER_ACRE, acres_of_polygon, centroid_of_polygon
from app.evidence.position import check_position
from app.evidence.rules import (
    code_flags,
    duplicate_photo,
    flags_for_position,
    too_fast,
)

_TO_WGS84 = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True).transform
_TO_UTM43 = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True).transform


def make_utm_rect_geojson(
    center_lat: float,
    center_lon: float,
    width_m: float,
    height_m: float,
) -> str:
    """Build a GeoJSON Polygon rectangle centered at (center_lat, center_lon) with exact UTM dimensions."""
    from shapely.geometry import mapping

    cx, cy = _TO_UTM43(center_lon, center_lat)
    rect_utm = box(cx - width_m / 2.0, cy - height_m / 2.0, cx + width_m / 2.0, cy + height_m / 2.0)
    def _proj_wgs84(c):
        xs, ys = _TO_WGS84(c[:, 0], c[:, 1])
        o = c.copy()
        o[:, 0] = xs
        o[:, 1] = ys
        return o
    rect_wgs84 = shapely.transform(rect_utm, _proj_wgs84)
    return json.dumps(mapping(rect_wgs84))


@pytest.mark.parametrize(
    "target_acres,aspect",
    [
        (0.5, 1.0),   # 0.5 acre square
        (1.5, 1.0),   # 1.5 acre square
        (4.0, 1.0),   # 4.0 acre square
        (10.0, 2.0),  # 10.0 acre rectangle (2:1)
        (20.0, 1.0),  # 20.0 acre square
    ],
)
def test_five_reference_polygons_near_punjab_within_5_percent(target_acres, aspect):
    """BUILD_PLAN Tier 1 test: 5 reference polygons near 30.7 N, 76.6 E from 0.5 to 20 acres within 5%."""
    area_m2 = target_acres * SQM_PER_ACRE
    width_m = math.sqrt(area_m2 * aspect)
    height_m = area_m2 / width_m

    geojson_str = make_utm_rect_geojson(30.7, 76.6, width_m, height_m)
    computed = acres_of_polygon(geojson_str)
    rel_error = abs(computed - target_acres) / target_acres
    assert rel_error <= 0.05, f"Expected ~{target_acres} ac, got {computed} ac"

    c_lat, c_lon = centroid_of_polygon(geojson_str)
    assert abs(c_lat - 30.7) < 0.01
    assert abs(c_lon - 76.6) < 0.01


def test_invalid_self_intersecting_polygon_rejected():
    """Bowtie self-intersecting polygon must raise ValueError."""
    bowtie = {
        "type": "Polygon",
        "coordinates": [
            [
                [76.600, 30.700],
                [76.602, 30.702],
                [76.602, 30.700],
                [76.600, 30.702],
                [76.600, 30.700],
            ]
        ],
    }
    with pytest.raises(ValueError):
        acres_of_polygon(bowtie)


def test_E1_fix_inside_plot_gives_distance_0_and_plausible():
    """E1: A fix inside the plot -> plausible: true, distance_to_plot_m: 0."""
    poly_json = make_utm_rect_geojson(30.7000, 76.6000, 100.0, 100.0)
    plot = {"geojson": poly_json, "acres": 2.47}
    res = check_position(30.7000, 76.6000, accuracy_m=12.0, plot=plot)
    assert res["distance_to_plot_m"] == 0.0
    assert res["plausible"] is True
    assert res["position_state"] == "plausible"
    assert flags_for_position(res["position_state"], res["plausible"]) == []


def test_E2_fix_25m_outside_with_40m_accuracy_is_plausible():
    """E2: A fix 25 m outside, reported accuracy 40 m -> plausible: true (tolerance max(30, 40) = 40)."""
    poly_json = make_utm_rect_geojson(30.7000, 76.6000, 100.0, 100.0)
    plot = {"geojson": poly_json, "acres": 2.47}

    # Move 75m north of center (25m outside the 100m box whose top edge is 50m north of center)
    cx, cy = _TO_UTM43(76.6000, 30.7000)
    lon_25m, lat_25m = _TO_WGS84(cx, cy + 75.0)

    res = check_position(lat_25m, lon_25m, accuracy_m=40.0, plot=plot)
    assert 23.0 <= res["distance_to_plot_m"] <= 27.0
    assert res["plausible"] is True
    assert res["position_state"] == "plausible"


def test_E3_fix_200m_away_is_mismatch_and_flagged():
    """E3: A fix 200 m away -> plausible: false, flag position_mismatch."""
    poly_json = make_utm_rect_geojson(30.7000, 76.6000, 100.0, 100.0)
    plot = {"geojson": poly_json, "acres": 2.47}

    cx, cy = _TO_UTM43(76.6000, 30.7000)
    lon_200m, lat_200m = _TO_WGS84(cx, cy + 250.0)  # 200m outside top edge

    res = check_position(lat_200m, lon_200m, accuracy_m=15.0, plot=plot)
    assert res["plausible"] is False
    assert res["position_state"] == "mismatch"
    assert flags_for_position(res["position_state"], res["plausible"]) == ["position_mismatch"]


def test_E4_accuracy_worse_than_100m_flags_position_mismatch():
    """E4: Reported accuracy worse than 100 m -> plausible: false, flag position_mismatch."""
    poly_json = make_utm_rect_geojson(30.7000, 76.6000, 100.0, 100.0)
    plot = {"geojson": poly_json, "acres": 2.47}

    res = check_position(30.7000, 76.6000, accuracy_m=150.0, plot=plot)
    assert res["plausible"] is False
    assert res["position_state"] == "mismatch"
    assert flags_for_position(res["position_state"], res["plausible"]) == ["position_mismatch"]


def test_pin_and_acres_circle_position_check():
    """With only a pin and acres, treat plot as a circle of that area around the pin."""
    plot = {"pin_lat": 30.7000, "pin_lon": 76.6000, "acres": 4.0}
    res_inside = check_position(30.7000, 76.6000, accuracy_m=10.0, plot=plot)
    assert res_inside["distance_to_plot_m"] == 0.0
    assert res_inside["plausible"] is True


def test_E5_too_fast_5_acres_in_10_minutes():
    """E5: 5 acres closed in 10 minutes -> too_fast True."""
    t0 = datetime(2026, 10, 25, 8, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=10)
    assert too_fast(t0, t1, acres=5.0, min_per_acre=25) is True

    # 5 acres in 130 minutes (>= 125 minutes) -> False
    t2 = t0 + timedelta(minutes=130)
    assert too_fast(t0, t2, acres=5.0, min_per_acre=25) is False


def test_E6_exact_duplicate_photo_flagged():
    """E6: The same file uploaded on two jobs -> duplicate_photo True."""
    raw_bytes = b"\xff\xd8\xffsample-field-image-bytes"
    sha = hashlib.sha256(raw_bytes).hexdigest()
    assert duplicate_photo(sha, ["abc123", sha]) is True


def test_E7_resized_copy_has_different_sha256_and_is_not_flagged():
    """E7: Document the limit of SHA-256 on purpose: a resized/re-encoded photo has a different hash and is not flagged."""
    original_bytes = b"\xff\xd8\xfforiginal-1600px-jpeg-bytes"
    resized_bytes = b"\xff\xd8\xffresized-800px-jpeg-bytes"
    sha_orig = hashlib.sha256(original_bytes).hexdigest()
    sha_resized = hashlib.sha256(resized_bytes).hexdigest()

    assert sha_orig != sha_resized
    assert duplicate_photo(sha_resized, [sha_orig]) is False


def test_E8_service_code_flags():
    """E8: Correct service code -> ([], True). Wrong or missing -> flag, never blocks."""
    flags_ok, confirmed_ok = code_flags("4821", "4821")
    assert flags_ok == []
    assert confirmed_ok is True

    flags_missing, confirmed_missing = code_flags("4821", None)
    assert flags_missing == ["code_missing"]
    assert confirmed_missing is False

    flags_wrong, confirmed_wrong = code_flags("4821", "9999")
    assert flags_wrong == ["code_wrong"]
    assert confirmed_wrong is False
