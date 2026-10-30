"""Rules, invariants and determinism tests for pure scheduler plan() (C1-C8, C10-C13)."""

import json
from dataclasses import asdict
from datetime import date, datetime, timezone

from app.scheduler.plan import (
    CentreIn,
    ExistingSlot,
    MachineIn,
    Plan,
    RequestIn,
    Settings,
    plan,
)

DEFAULT_SETTINGS = Settings(max_radius_km=25.0, road_factor=1.3)

HOME_CENTRE = CentreIn(
    id=1,
    name="Kisan Seva Kendra Nabha",
    lat=30.3700,
    lon=76.1500,
    is_home=True,
    service_types=("super_seeder", "happy_seeder", "baler"),
)
CENTRE_B = CentreIn(
    id=2,
    name="Centre B",
    lat=30.4300,
    lon=76.2000,
    is_home=False,
    service_types=("super_seeder", "baler", "mulcher"),
)
CENTRES = [HOME_CENTRE, CENTRE_B]


def test_C1_exact_capacity_match_is_allowed():
    """C1: Request of 6 acres, machine-day has exactly 6 free -> Scheduled."""
    today = date(2026, 10, 10)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=600,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 12),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=600,
        status="active",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 1
    assert p.assignments[0].service_date == date(2026, 10, 10)


def test_C2_request_exceeding_capacity_not_placed():
    """C2: Request of 6.5 acres on machine with 6 free -> Not placed on that day."""
    today = date(2026, 10, 10)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=650,  # 6.5 acres
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 10),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=600,  # 6.0 acres
        status="active",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 0
    assert len(p.misses) == 1
    assert p.misses[0].reason_code == "NO_CAPACITY"


def test_C3_zero_free_capacity_gives_no_capacity():
    """C3: Zero free capacity before deadline -> NO_CAPACITY."""
    today = date(2026, 10, 10)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=300,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 10),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    existing = [ExistingSlot(machine_id=1, service_date=today, acres_x100=800)]
    p = plan([req], [machine], CENTRES, existing, today, DEFAULT_SETTINGS)
    assert len(p.misses) == 1
    assert p.misses[0].reason_code == "NO_CAPACITY"


def test_C4_no_compatible_machine():
    """C4: Baler job, only seeders exist -> NO_COMPATIBLE_MACHINE."""
    today = date(2026, 10, 10)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="baler",
        acres_x100=500,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 15),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder", "happy_seeder"),
        capacity_acres_x100=800,
        status="active",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.misses) == 1
    assert p.misses[0].reason_code == "NO_COMPATIBLE_MACHINE"


def test_C5_compatible_machine_inactive_gives_machine_unavailable():
    """C5: Compatible machine inactive across whole window -> MACHINE_UNAVAILABLE."""
    today = date(2026, 10, 10)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=300,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 15),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="inactive",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.misses) == 1
    assert p.misses[0].reason_code == "MACHINE_UNAVAILABLE"


def test_C6_priority_order_deadline_created_at_id():
    """C6: Two requests, same deadline, room for one -> Earlier created_at wins."""
    today = date(2026, 10, 10)
    req1 = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc),  # later
        service_type="super_seeder",
        acres_x100=600,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 10),
    )
    req2 = RequestIn(
        id=2,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),  # earlier
        service_type="super_seeder",
        acres_x100=600,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 10),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    p = plan([req1, req2], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 1
    assert p.assignments[0].request_id == 2  # req2 won
    assert len(p.misses) == 1
    assert p.misses[0].request_id == 1


def test_C7_tie_breaking_lower_machine_id_wins():
    """C7: Two machines, equal cost -> Lower machine id wins."""
    today = date(2026, 10, 10)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=400,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 10),
        lat=HOME_CENTRE.lat,
        lon=HOME_CENTRE.lon,
    )
    m1 = MachineIn(id=2, service_types=("super_seeder",), capacity_acres_x100=800, status="active")
    m2 = MachineIn(id=1, service_types=("super_seeder",), capacity_acres_x100=800, status="active")
    p = plan([req], [m1, m2], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 1
    assert p.assignments[0].machine_id == 1  # lower id wins


def test_C8_strict_determinism_byte_for_byte():
    """C8: Same input run twice produces byte-for-byte identical JSON serialization."""
    today = date(2026, 10, 10)
    requests = [
        RequestIn(
            id=i,
            created_at=datetime(2026, 10, 10, i, 0, tzinfo=timezone.utc),
            service_type="super_seeder",
            acres_x100=300 + i * 50,
            harvest_date=date(2026, 10, 10),
            deadline_date=date(2026, 10, 10 + (i % 3)),
            lat=30.37 + 0.01 * i,
            lon=76.15 + 0.01 * i,
        )
        for i in range(1, 6)
    ]
    machines = [
        MachineIn(id=1, service_types=("super_seeder",), capacity_acres_x100=800, status="active"),
        MachineIn(id=2, service_types=("super_seeder",), capacity_acres_x100=800, status="active"),
    ]
    p1 = plan(requests, machines, CENTRES, [], today, DEFAULT_SETTINGS)
    p2 = plan(requests, machines, CENTRES, [], today, DEFAULT_SETTINGS)

    # Serialize to JSON with sort_keys=True
    def serialize_plan(p: Plan) -> str:
        data = {
            "assignments": [asdict(a) for a in p.assignments],
            "misses": [asdict(m) for m in p.misses],
        }
        # Convert date objects to str for json
        return json.dumps(data, sort_keys=True, default=str)

    s1 = serialize_plan(p1)
    s2 = serialize_plan(p2)
    assert s1 == s2


def test_C10_and_C11_invariants():
    """C10 & C11: Invariant checks over a hand-built scenario."""
    today = date(2026, 10, 10)
    requests = [
        RequestIn(id=1, created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc), service_type="super_seeder", acres_x100=300, harvest_date=date(2026, 10, 10), deadline_date=date(2026, 10, 12)),
        RequestIn(id=2, created_at=datetime(2026, 10, 10, 8, 30, tzinfo=timezone.utc), service_type="super_seeder", acres_x100=500, harvest_date=date(2026, 10, 10), deadline_date=date(2026, 10, 11)),
        RequestIn(id=3, created_at=datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc), service_type="super_seeder", acres_x100=600, harvest_date=date(2026, 10, 10), deadline_date=date(2026, 10, 11)),
    ]
    machine = MachineIn(id=1, service_types=("super_seeder",), capacity_acres_x100=800, status="active")
    p = plan(requests, [machine], CENTRES, [], today, DEFAULT_SETTINGS)

    # Invariant 1: No machine-day over capacity
    day_capacity: dict[date, int] = {}
    for a in p.assignments:
        req = next(r for r in requests if r.id == a.request_id)
        day_capacity[a.service_date] = day_capacity.get(a.service_date, 0) + req.acres_x100
    for d, used in day_capacity.items():
        assert used <= machine.capacity_acres_x100, f"Machine-day {d} over capacity: {used} > {machine.capacity_acres_x100}"

    # Invariant 2: No slot outside [max(today, harvest), deadline]
    for a in p.assignments:
        req = next(r for r in requests if r.id == a.request_id)
        assert a.service_date >= max(today, req.harvest_date)
        assert a.service_date <= req.deadline_date

    # Invariant 3: Every miss has reason_code, sentence, next_action
    for m in p.misses:
        assert m.reason_code in ("INVALID_REQUEST", "DEADLINE_PASSED", "NO_COMPATIBLE_MACHINE", "MACHINE_UNAVAILABLE", "TRAVEL_INFEASIBLE", "NO_CAPACITY")
        assert len(m.reason) > 0
        assert m.next_action is not None

    # Invariant 4: C11 - Every request is in exactly one state
    assigned_ids = {a.request_id for a in p.assignments}
    missed_ids = {m.request_id for m in p.misses}
    all_input_ids = {r.id for r in requests}
    assert assigned_ids.isdisjoint(missed_ids)
    assert assigned_ids | missed_ids == all_input_ids


def test_C12_travel_infeasible_beyond_radius():
    """C12: A field estimated 40 km away (over 25 km max radius) -> TRAVEL_INFEASIBLE."""
    today = date(2026, 10, 10)
    # Distance ~37 km from (30.37, 76.15) to (30.70, 76.15)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=300,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 15),
        lat=30.7000,
        lon=76.1500,
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.misses) == 1
    assert p.misses[0].reason_code == "TRAVEL_INFEASIBLE"
    assert p.misses[0].nearest_alternative is not None


def test_reason_code_precedence_order():
    """Reason order: MACHINE_UNAVAILABLE before TRAVEL_INFEASIBLE before NO_CAPACITY."""
    today = date(2026, 10, 10)
    # Machine inactive and field far away -> MACHINE_UNAVAILABLE takes precedence
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=300,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 15),
        lat=30.7000,  # far away
        lon=76.1500,
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="inactive",  # inactive
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.misses) == 1
    assert p.misses[0].reason_code == "MACHINE_UNAVAILABLE"


def test_seq_renumbering_nearest_neighbour():
    """Seq renumbering by nearest neighbour starting from centre, ties broken by id."""
    today = date(2026, 10, 10)
    # Point 1: 5 km away (id 1)
    # Point 2: 2 km away (id 2)
    # Point 3: 3 km from point 2 (id 3)
    req1 = RequestIn(id=1, created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc), service_type="super_seeder", acres_x100=200, harvest_date=today, deadline_date=today, lat=30.41, lon=76.15)
    req2 = RequestIn(id=2, created_at=datetime(2026, 10, 10, 8, 1, tzinfo=timezone.utc), service_type="super_seeder", acres_x100=200, harvest_date=today, deadline_date=today, lat=30.38, lon=76.15)
    machine = MachineIn(id=1, service_types=("super_seeder",), capacity_acres_x100=800, status="active")

    p = plan([req1, req2], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    # req2 is closer to centre (30.37), so seq 1 must be req2, seq 2 must be req1
    assignments_by_req = {a.request_id: a for a in p.assignments}
    assert assignments_by_req[2].seq == 1
    assert assignments_by_req[1].seq == 2


def test_explanation_sentences_match_templates():
    """Explanation sentences match CONTRACT.md section 8 table."""
    today = date(2026, 10, 20)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=320,  # 3.2 acres
        harvest_date=date(2026, 10, 18),
        deadline_date=date(2026, 10, 24),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 1
    # Check "Scheduled on 20 Oct on Super Seeder: the earliest day with 3.2 free acres before the deadline of 24 Oct."
    assert "Scheduled on 20 Oct on" in p.assignments[0].explanation
    assert "the earliest day with 3.2 free acres before the deadline of 24 Oct." in p.assignments[0].explanation


def test_naive_created_at_is_treated_as_utc():
    """Found by ruff (F821) in pilot item C11: a naive created_at used to raise NameError."""
    today = date(2026, 10, 10)
    naive = RequestIn(
        id=2,
        created_at=datetime(2026, 10, 10, 8, 0),
        service_type="super_seeder",
        acres_x100=300,
        harvest_date=today,
        deadline_date=today,
    )
    aware = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=300,
        harvest_date=today,
        deadline_date=today,
    )
    machine = MachineIn(id=1, service_types=("super_seeder",), capacity_acres_x100=300, status="active")
    p = plan([aware, naive], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    # 08:00 naive (UTC) is earlier than 09:00 UTC, so the naive request wins the only space.
    assert [a.request_id for a in p.assignments] == [2]
