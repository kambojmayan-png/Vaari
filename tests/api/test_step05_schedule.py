"""API tests for Step 05: scheduler implementation, C9, B7 (second half), C11, will-miss."""

from datetime import timedelta

from app import clock


def test_C9_machine_inactive_reflows_plan(client, auth_headers):
    """Test C9: A machine set inactive cancels unstarted slots and reflows plan."""
    today = clock.today()
    # 1. Create one machine
    m_res = client.post(
        "/api/machines",
        json={
            "name": "Super Seeder Single",
            "type": "Super Seeder",
            "service_types": ["super_seeder"],
            "capacity_acres_per_day": 8.0,
        },
        headers=auth_headers,
    )
    m_id = m_res.json()["id"]

    # 2. Create request
    r_res = client.post(
        "/api/requests",
        json={
            "phone": "9876543210",
            "village": "Pind Kalan",
            "acres": 4.0,
            "service_type": "super_seeder",
            "harvest_date": str(today),
            "deadline_date": str(today + timedelta(days=2)),
            "consent_service": True,
        },
        headers=auth_headers,
    )
    req_id = r_res.json()["id"]

    # 3. Trigger schedule run
    client.post("/api/schedule/run", headers=auth_headers)
    req_after_run = client.get(f"/api/requests/{req_id}", headers=auth_headers).json()
    assert req_after_run["status"] == "scheduled"
    assert req_after_run["slot"] is not None

    # 4. Set machine inactive
    client.patch(f"/api/machines/{m_id}", json={"status": "inactive"}, headers=auth_headers)

    # 5. Check request status after reflow
    req_after_inactive = client.get(f"/api/requests/{req_id}", headers=auth_headers).json()
    assert req_after_inactive["status"] == "will_miss"
    assert req_after_inactive["explanation"]["reason_code"] in ("MACHINE_UNAVAILABLE", "NO_COMPATIBLE_MACHINE")


def test_B7_second_half_patch_harvest_date_plans_request(client, auth_headers):
    """Test B7 (second half): a needs_info request gets a harvest date by PATCH and is planned."""
    today = clock.today()
    # 1. Create machine
    client.post(
        "/api/machines",
        json={
            "name": "Super Seeder B7",
            "type": "Super Seeder",
            "service_types": ["super_seeder"],
            "capacity_acres_per_day": 8.0,
        },
        headers=auth_headers,
    )

    # 2. Create request without harvest date -> needs_info
    r_res = client.post(
        "/api/requests",
        json={
            "phone": "9876543220",
            "village": "Pind Kalan",
            "acres": 3.0,
            "service_type": "super_seeder",
            "consent_service": True,
        },
        headers=auth_headers,
    )
    req_id = r_res.json()["id"]
    assert r_res.json()["status"] == "needs_info"

    # 3. PATCH with harvest_date
    patch_res = client.patch(
        f"/api/requests/{req_id}",
        json={"harvest_date": str(today)},
        headers=auth_headers,
    )
    assert patch_res.status_code == 200

    # 4. Run schedule
    client.post("/api/schedule/run", headers=auth_headers)
    req = client.get(f"/api/requests/{req_id}", headers=auth_headers).json()
    assert req["status"] == "scheduled"
    assert req["harvest_date"] == str(today)


def test_C11_every_request_in_exactly_one_status(client, auth_headers):
    """Test C11: after API run, every request is in exactly one status."""
    today = clock.today()
    client.post(
        "/api/machines",
        json={
            "name": "Machine C11",
            "type": "Super Seeder",
            "service_types": ["super_seeder"],
            "capacity_acres_per_day": 5.0,
        },
        headers=auth_headers,
    )

    # Req 1: fits capacity
    client.post(
        "/api/requests",
        json={
            "phone": "9876543231",
            "village": "Pind Kalan",
            "acres": 4.0,
            "service_type": "super_seeder",
            "harvest_date": str(today),
            "deadline_date": str(today),
            "consent_service": True,
        },
        headers=auth_headers,
    )
    # Req 2: exceeds remaining capacity today -> will_miss
    client.post(
        "/api/requests",
        json={
            "phone": "9876543232",
            "village": "Pind Kalan",
            "acres": 4.0,
            "service_type": "super_seeder",
            "harvest_date": str(today),
            "deadline_date": str(today),
            "consent_service": True,
        },
        headers=auth_headers,
    )
    # Req 3: needs info
    client.post(
        "/api/requests",
        json={
            "phone": "9876543233",
            "village": "Pind Kalan",
            "acres": 2.0,
            "service_type": "super_seeder",
            "consent_service": True,
        },
        headers=auth_headers,
    )

    run_res = client.post("/api/schedule/run", headers=auth_headers)
    assert run_res.status_code == 200
    counts = run_res.json()
    assert counts["total"] == 3
    assert counts["scheduled"] == 1
    assert counts["will_miss"] == 1
    assert counts["needs_info"] == 1

    all_reqs = client.get("/api/requests", headers=auth_headers).json()
    valid_statuses = {"needs_info", "open", "scheduled", "done", "will_miss", "cancelled"}
    for r in all_reqs:
        assert r["status"] in valid_statuses


def test_will_miss_never_contains_phone_numbers(client, auth_headers):
    """Will-miss list endpoint never exposes phone numbers."""
    secret_phone = "9876543299"
    today = clock.today()
    # Create request with no compatible machine
    client.post(
        "/api/requests",
        json={
            "phone": secret_phone,
            "village": "Far Away Pind",
            "acres": 5.0,
            "service_type": "baler",  # no baler
            "harvest_date": str(today),
            "deadline_date": str(today + timedelta(days=2)),
            "consent_service": True,
        },
        headers=auth_headers,
    )

    client.post("/api/schedule/run", headers=auth_headers)

    res = client.get("/api/schedule/will-miss", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 1
    raw_text = res.text
    assert secret_phone not in raw_text
    assert "phone" not in data[0]
