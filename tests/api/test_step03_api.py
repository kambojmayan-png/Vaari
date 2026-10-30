"""API tests for Step 03: requests, machines and plots."""



def test_request_lifecycle_crud(client, auth_headers):
    # Create
    create_payload = {
        "phone": "9876543210",
        "name": "Harpreet Singh",
        "village": "Pind Kalan",
        "lat": 30.7333,
        "lon": 76.7794,
        "acres": 3.2,
        "service_type": "super_seeder",
        "harvest_date": "2026-10-20",
        "consent_service": True,
        "consent_evidence": True,
        "consent_share": True,
    }
    res = client.post("/api/requests", json=create_payload, headers=auth_headers)
    assert res.status_code == 201
    data = res.json()
    req_id = data["id"]
    assert data["farmer"]["phone"] == "9876543210"
    assert data["farmer"]["name"] == "Harpreet Singh"
    assert data["village"] == "Pind Kalan"
    assert data["acres"] == 3.2
    assert data["service_type"] == "super_seeder"
    assert data["status"] in ("open", "scheduled", "will_miss")
    assert data["harvest_date"] == "2026-10-20"
    assert data["sow_by"] == "2026-11-09"
    assert data["deadline_date"] == "2026-11-09"

    # Get
    res_get = client.get(f"/api/requests/{req_id}", headers=auth_headers)
    assert res_get.status_code == 200
    assert res_get.json()["id"] == req_id

    # List and filter
    res_list = client.get("/api/requests?village=Pind Kalan&service_type=super_seeder", headers=auth_headers)
    assert res_list.status_code == 200
    items = res_list.json()
    assert len(items) == 1
    assert items[0]["id"] == req_id

    # Filter with no match
    res_empty = client.get("/api/requests?village=NonExistent", headers=auth_headers)
    assert res_empty.status_code == 200
    assert len(res_empty.json()) == 0

    # Patch
    patch_payload = {"acres": 4.5, "name": "Harpreet S."}
    res_patch = client.patch(f"/api/requests/{req_id}", json=patch_payload, headers=auth_headers)
    assert res_patch.status_code == 200
    patched = res_patch.json()
    assert patched["acres"] == 4.5
    assert patched["farmer"]["name"] == "Harpreet S."

    # Delete
    res_del = client.delete(f"/api/requests/{req_id}", headers=auth_headers)
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "cancelled"

    # Cannot patch cancelled request
    res_invalid_patch = client.patch(f"/api/requests/{req_id}", json={"acres": 5.0}, headers=auth_headers)
    assert res_invalid_patch.status_code == 409
    assert res_invalid_patch.json()["error_code"] == "INVALID_TRANSITION"


def test_B3_deadline_date_before_harvest_date_rejected(client, auth_headers):
    """Test B3: deadline_date < harvest_date rejected with 422 VALIDATION_ERROR on field deadline_date."""
    payload = {
        "phone": "9876543210",
        "village": "Pind Kalan",
        "acres": 3.0,
        "service_type": "super_seeder",
        "harvest_date": "2026-10-25",
        "deadline_date": "2026-10-20",  # before harvest
        "consent_service": True,
    }
    res = client.post("/api/requests", json=payload, headers=auth_headers)
    assert res.status_code == 422
    err = res.json()
    assert err["error_code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "deadline_date"


def test_B7_first_half_no_harvest_date_gives_needs_info(client, auth_headers):
    """Test B7 (first half): creation without harvest_date gives status needs_info and null dates."""
    payload = {
        "phone": "9876543211",
        "village": "Pind Kalan",
        "acres": 2.5,
        "service_type": "happy_seeder",
        "consent_service": True,
    }
    res = client.post("/api/requests", json=payload, headers=auth_headers)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "needs_info"
    assert data["harvest_date"] is None
    assert data["sow_by"] is None
    assert data["deadline_date"] is None


def test_consent_service_false_rejected(client, auth_headers):
    payload = {
        "phone": "9876543212",
        "village": "Pind Kalan",
        "acres": 2.5,
        "service_type": "super_seeder",
        "consent_service": False,
    }
    res = client.post("/api/requests", json=payload, headers=auth_headers)
    assert res.status_code == 422
    err = res.json()
    assert err["error_code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "consent_service"


def test_invalid_phone_9_digits_rejected(client, auth_headers):
    payload = {
        "phone": "987654321",  # 9 digits
        "village": "Pind Kalan",
        "acres": 2.5,
        "service_type": "super_seeder",
        "consent_service": True,
    }
    res = client.post("/api/requests", json=payload, headers=auth_headers)
    assert res.status_code == 422
    err = res.json()
    assert err["error_code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "phone"


def test_acres_below_minimum_rejected(client, auth_headers):
    payload = {
        "phone": "9876543210",
        "village": "Pind Kalan",
        "acres": 0.1,  # below 0.25
        "service_type": "super_seeder",
        "consent_service": True,
    }
    res = client.post("/api/requests", json=payload, headers=auth_headers)
    assert res.status_code == 422
    err = res.json()
    assert err["error_code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "acres"


def test_S11_string_for_acres_gives_validation_error_shape(client, auth_headers):
    """Test S11: string for acres gives VALIDATION_ERROR with details.field 'acres'."""
    payload = {
        "phone": "9876543210",
        "village": "Pind Kalan",
        "acres": "three",
        "service_type": "super_seeder",
        "consent_service": True,
    }
    res = client.post("/api/requests", json=payload, headers=auth_headers)
    assert res.status_code == 422
    err = res.json()
    assert err["error_code"] == "VALIDATION_ERROR"
    assert err["details"]["field"] == "acres"


def test_machine_create_list_and_patch_inactive(client, auth_headers):
    payload = {
        "name": "Super Seeder 01",
        "type": "Super Seeder",
        "service_types": ["super_seeder"],
        "capacity_acres_per_day": 8.0,
    }
    res = client.post("/api/machines", json=payload, headers=auth_headers)
    assert res.status_code == 201
    m = res.json()
    m_id = m["id"]
    assert m["name"] == "Super Seeder 01"
    assert m["capacity_acres_per_day"] == 8.0
    assert m["status"] == "active"
    assert m["driver_path"].startswith("/driver/")

    # List
    res_list = client.get("/api/machines", headers=auth_headers)
    assert res_list.status_code == 200
    assert any(item["id"] == m_id for item in res_list.json())

    # Patch to inactive
    res_patch = client.patch(f"/api/machines/{m_id}", json={"status": "inactive"}, headers=auth_headers)
    assert res_patch.status_code == 200
    assert res_patch.json()["status"] == "inactive"


def test_plots_api(client, auth_headers):
    payload = {
        "farmer_phone": "9876543210",
        "village": "Nabha",
        "pin_lat": 30.37,
        "pin_lon": 76.15,
        "acres": 5.0,
    }
    res = client.post("/api/plots", json=payload, headers=auth_headers)
    assert res.status_code == 201
    plot = res.json()
    plot_id = plot["id"]
    assert plot["village_name"] == "Nabha"
    assert plot["acres"] == 5.0
    assert plot["location_source"] == "pin"

    # List
    res_list = client.get("/api/plots", headers=auth_headers)
    assert res_list.status_code == 200
    assert any(p["id"] == plot_id for p in res_list.json())

    # Get
    res_get = client.get(f"/api/plots/{plot_id}", headers=auth_headers)
    assert res_get.status_code == 200
    assert res_get.json()["id"] == plot_id


def test_S9_unauthorized_without_passcode_on_all_route_groups(client):
    """Test S9: 401 UNAUTHORIZED on each route group without passcode."""
    routes = [
        ("POST", "/api/requests", {"phone": "9876543210", "village": "Pind", "acres": 1.0, "service_type": "super_seeder", "consent_service": True}),
        ("GET", "/api/requests", None),
        ("POST", "/api/machines", {"name": "M", "type": "T", "service_types": ["baler"], "capacity_acres_per_day": 5.0}),
        ("GET", "/api/machines", None),
        ("POST", "/api/plots", {"farmer_phone": "9876543210", "village": "Pind", "acres": 1.0}),
        ("GET", "/api/plots", None),
    ]
    for method, path, body in routes:
        if method == "POST":
            res = client.post(path, json=body)
        else:
            res = client.get(path)
        assert res.status_code == 401, f"{method} {path} returned {res.status_code} instead of 401"
        data = res.json()
        assert data["error_code"] == "UNAUTHORIZED"
