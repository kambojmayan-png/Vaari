"""API tests for Step 07: E1-E10 through the API, polygon plots, and record verification."""

import json

import shapely
from pyproj import Transformer
from shapely.geometry import box, mapping

from app import clock
from app.models import Plot, Request, Slot
from tests.fixtures.synthetic_photos import TINY_JPEG

_TO_WGS84 = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True).transform
_TO_UTM43 = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True).transform

PHOTO_A = TINY_JPEG[:20] + b"\xff\xfe\x00\x07PHOTO_A" + TINY_JPEG[20:]
PHOTO_B = TINY_JPEG[:20] + b"\xff\xfe\x00\x07PHOTO_B" + TINY_JPEG[20:]
PHOTO_C = TINY_JPEG[:20] + b"\xff\xfe\x00\x07PHOTO_C" + TINY_JPEG[20:]


def make_square_polygon_geojson(lat: float, lon: float, side_m: float = 100.0) -> str:
    cx, cy = _TO_UTM43(lon, lat)
    half = side_m / 2.0
    poly_utm = box(cx - half, cy - half, cx + half, cy + half)
    def _proj_wgs84(c):
        xs, ys = _TO_WGS84(c[:, 0], c[:, 1])
        o = c.copy()
        o[:, 0] = xs
        o[:, 1] = ys
        return o
    poly_wgs = shapely.transform(poly_utm, _proj_wgs84)
    return json.dumps(mapping(poly_wgs))


def setup_slot_with_polygon(client, auth_headers, temp_db, phone: str):
    today = clock.today()
    client.post(
        "/api/machines",
        json={
            "name": f"Machine-{phone[-4:]}",
            "type": "Super Seeder",
            "service_types": ["super_seeder"],
            "capacity_acres_per_day": 15.0,
        },
        headers=auth_headers,
    )
    r_res = client.post(
        "/api/requests",
        json={
            "phone": phone,
            "village": "Pind Kalan",
            "lat": 30.7333,
            "lon": 76.7794,
            "acres": 2.5,
            "service_type": "super_seeder",
            "harvest_date": str(today),
            "deadline_date": str(today),
            "consent_service": True,
            "consent_evidence": True,
            "consent_share": True,
        },
        headers=auth_headers,
    )
    req_id = r_res.json()["id"]

    # Attach a 100m x 100m polygon centered at (30.7333, 76.7794)
    poly_str = make_square_polygon_geojson(30.7333, 76.7794, 100.0)
    session = temp_db()
    req_orm = session.query(Request).filter_by(id=req_id).one()
    plot_orm = session.query(Plot).filter_by(id=req_orm.plot_id).one()
    plot_orm.geojson = poly_str
    plot_orm.location_source = "polygon"
    slot_orm = session.query(Slot).filter_by(request_id=req_id).one()
    slot_id = slot_orm.id
    slot_token = slot_orm.link_token
    service_code = slot_orm.service_code
    session.commit()
    session.close()

    return slot_id, slot_token, service_code, req_id


def test_post_plots_computes_geojson_area_and_warns_when_acres_differs(client, auth_headers):
    # 100m x 100m = 10,000 m² = ~2.47 acres
    poly_str = make_square_polygon_geojson(30.7333, 76.7794, 100.0)
    res = client.post(
        "/api/plots",
        headers=auth_headers,
        json={
            "farmer_phone": "9876543210",
            "village": "Pind Kalan",
            "acres": 5.0,  # differs from 2.47 by > 10%
            "geojson": poly_str,
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["location_source"] == "polygon"
    assert 2.40 <= data["acres"] <= 2.55  # kept polygon's computed value
    assert data["warning"] is not None
    assert "10%" in data["warning"]


def test_E1_E2_E5_E8_plausible_positions_live_too_fast_and_record_verifies(
    client, auth_headers, temp_db
):
    slot_id, slot_token, service_code, _ = setup_slot_with_polygon(
        client, auth_headers, temp_db, "9800000001"
    )

    # E1: Start inside plot (30.7333, 76.7794) -> distance 0, plausible True
    start_res = client.post(
        f"/api/slots/{slot_id}/start",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("start.jpg", PHOTO_A, "image/jpeg")},
        data={"lat": 30.7333, "lon": 76.7794, "accuracy_m": 10.0},
    )
    assert start_res.status_code == 200
    s_ev = start_res.json()["evidence"]
    assert s_ev["distance_to_plot_m"] == 0.0
    assert s_ev["plausible"] is True
    assert s_ev["position_state"] == "plausible"

    # E2: Done 25m outside top edge (75m north of center) with accuracy 40m -> plausible True
    cx, cy = _TO_UTM43(76.7794, 30.7333)
    lon_25m, lat_25m = _TO_WGS84(cx, cy + 75.0)

    # Completed within 1 minute -> triggers too_fast (E5), with matching service code (E8)
    done_res = client.post(
        f"/api/slots/{slot_id}/done",
        headers={"X-Vaari-Slot-Token": slot_token},
        files={"photo": ("done.jpg", PHOTO_B, "image/jpeg")},
        data={
            "lat": lat_25m,
            "lon": lon_25m,
            "accuracy_m": 40.0,
            "service_code": service_code,
        },
    )
    assert done_res.status_code == 200
    d_json = done_res.json()
    assert d_json["evidence"]["plausible"] is True
    assert d_json["evidence"]["position_state"] == "plausible"
    assert "too_fast" in d_json["flags"]
    assert "position_mismatch" not in d_json["flags"]
    assert "code_missing" not in d_json["flags"]
    assert "code_wrong" not in d_json["flags"]
    assert d_json["needs_review"] is True

    # Record shows plausible positions, no "position not checked" badge, and hash verifies
    record_token = d_json["record_url"].split("/")[-1]
    rec = client.get(f"/api/records/{record_token}").json()
    assert rec["start_position"] == "plausible"
    assert rec["done_position"] == "plausible"
    assert "position not checked" not in rec["badges"]
    assert rec["farmer_confirmed"] is True

    ver = client.get(f"/api/records/{record_token}/verify").json()
    assert ver["match"] is True


def test_E3_E4_E6_E8_mismatch_duplicate_photo_and_wrong_code_through_api(
    client, auth_headers, temp_db
):
    # Job 1 uploads PHOTO_A
    slot1_id, slot1_token, code1, _ = setup_slot_with_polygon(
        client, auth_headers, temp_db, "9800000002"
    )
    client.post(
        f"/api/slots/{slot1_id}/start",
        headers={"X-Vaari-Slot-Token": slot1_token},
        files={"photo": ("s1.jpg", PHOTO_A, "image/jpeg")},
        data={"lat": 30.7333, "lon": 76.7794, "accuracy_m": 10.0},
    )
    client.post(
        f"/api/slots/{slot1_id}/done",
        headers={"X-Vaari-Slot-Token": slot1_token},
        files={"photo": ("d1.jpg", PHOTO_B, "image/jpeg")},
        data={"lat": 30.7333, "lon": 76.7794, "accuracy_m": 10.0, "service_code": code1},
    )

    # Job 2:
    # - Start 200m outside plot (E3)
    # - Done with accuracy 150m (E4), duplicate PHOTO_A from Job 1 (E6), and wrong code (E8)
    slot2_id, slot2_token, _, _ = setup_slot_with_polygon(
        client, auth_headers, temp_db, "9800000003"
    )
    cx, cy = _TO_UTM43(76.7794, 30.7333)
    lon_200m, lat_200m = _TO_WGS84(cx, cy + 250.0)

    s2_res = client.post(
        f"/api/slots/{slot2_id}/start",
        headers={"X-Vaari-Slot-Token": slot2_token},
        files={"photo": ("s2.jpg", PHOTO_C, "image/jpeg")},
        data={"lat": lat_200m, "lon": lon_200m, "accuracy_m": 15.0},
    )
    assert s2_res.status_code == 200
    assert s2_res.json()["evidence"]["plausible"] is False
    assert s2_res.json()["evidence"]["position_state"] == "mismatch"

    d2_res = client.post(
        f"/api/slots/{slot2_id}/done",
        headers={"X-Vaari-Slot-Token": slot2_token},
        files={"photo": ("d2.jpg", PHOTO_A, "image/jpeg")},  # duplicate of Job 1
        data={
            "lat": 30.7333,
            "lon": 76.7794,
            "accuracy_m": 150.0,  # > 100m accuracy -> mismatch
            "service_code": "0000" if code1 != "0000" else "9999",
        },
    )
    assert d2_res.status_code == 200
    d2_data = d2_res.json()
    flags = d2_data["flags"]
    assert "position_mismatch" in flags
    assert "exact_duplicate_photo" in flags
    assert "code_wrong" in flags
    assert d2_data["needs_review"] is True

    # Officer dashboard summary counts needs_review and lists flagged_jobs without names/phones
    dash = client.get("/api/dashboard/summary", headers=auth_headers).json()
    assert dash["needs_review"] >= 1
    assert len(dash["flagged_jobs"]) >= 1
    raw_dash = json.dumps(dash["flagged_jobs"])
    assert "9800000002" not in raw_dash
    assert "9800000003" not in raw_dash
