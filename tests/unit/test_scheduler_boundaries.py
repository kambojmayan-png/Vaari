"""Boundary tests B1 to B6 for pure scheduler plan()."""

from datetime import date, datetime, timezone

from app.scheduler.plan import (
    CentreIn,
    ExistingSlot,
    MachineIn,
    RequestIn,
    Settings,
    days_inclusive,
    plan,
)

DEFAULT_SETTINGS = Settings(max_radius_km=25.0, road_factor=1.3)
HOME_CENTRE = CentreIn(
    id=1,
    name="Kisan Seva Kendra Nabha",
    lat=30.7333,
    lon=76.7794,
    is_home=True,
    service_types=("super_seeder", "happy_seeder", "baler", "mulcher"),
)
CENTRES = [HOME_CENTRE]


def test_days_inclusive_yields_end_date():
    start = date(2026, 10, 10)
    end = date(2026, 10, 15)
    days = list(days_inclusive(start, end))
    assert len(days) == 6
    assert days[0] == start
    assert days[-1] == end


def test_B1_deadline_day_is_tried():
    """B1: Harvest 10 Oct, deadline 15 Oct, one machine free only on 15 Oct -> Scheduled on 15 Oct."""
    today = date(2026, 10, 10)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=400,  # 4 acres
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 15),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    # Busy on 10, 11, 12, 13, 14 Oct
    existing = [
        ExistingSlot(machine_id=1, service_date=date(2026, 10, d), acres_x100=800)
        for d in range(10, 15)
    ]

    p = plan([req], [machine], CENTRES, existing, today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 1
    assert p.assignments[0].service_date == date(2026, 10, 15)
    assert p.assignments[0].machine_id == 1


def test_B2_capacity_only_after_deadline_misses():
    """B2: Harvest 10 Oct, deadline 15 Oct, machine free only on 16 Oct -> will_miss, NO_CAPACITY."""
    today = date(2026, 10, 10)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=400,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 15),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    # Busy through 15 Oct
    existing = [
        ExistingSlot(machine_id=1, service_date=date(2026, 10, d), acres_x100=800)
        for d in range(10, 16)
    ]

    p = plan([req], [machine], CENTRES, existing, today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 0
    assert len(p.misses) == 1
    assert p.misses[0].reason_code == "NO_CAPACITY"


def test_B3_scheduler_defensive_invalid_request():
    """B3: Unit test request with deadline 9 Oct < harvest 10 Oct gives will_miss INVALID_REQUEST."""
    today = date(2026, 10, 5)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=400,
        harvest_date=date(2026, 10, 10),
        deadline_date=date(2026, 10, 9),  # deadline < harvest
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 0
    assert len(p.misses) == 1
    assert p.misses[0].reason_code == "INVALID_REQUEST"


def test_B4_deadline_equals_harvest_date():
    """B4: Deadline equals harvest date, machine free that day -> Scheduled on that day."""
    today = date(2026, 10, 12)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=300,
        harvest_date=date(2026, 10, 12),
        deadline_date=date(2026, 10, 12),
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 1
    assert p.assignments[0].service_date == date(2026, 10, 12)


def test_B5_deadline_before_today_gives_deadline_passed():
    """B5: Deadline before today -> will_miss, DEADLINE_PASSED."""
    today = date(2026, 10, 26)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=300,
        harvest_date=date(2026, 10, 20),
        deadline_date=date(2026, 10, 24),  # before today (26 Oct)
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 0
    assert len(p.misses) == 1
    assert p.misses[0].reason_code == "DEADLINE_PASSED"


def test_B6_harvest_in_future_no_slot_before_harvest():
    """B6: Harvest in the future -> No slot before harvest date."""
    today = date(2026, 10, 10)
    harvest = date(2026, 10, 15)
    deadline = date(2026, 10, 20)
    req = RequestIn(
        id=1,
        created_at=datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc),
        service_type="super_seeder",
        acres_x100=300,
        harvest_date=harvest,
        deadline_date=deadline,
    )
    machine = MachineIn(
        id=1,
        service_types=("super_seeder",),
        capacity_acres_x100=800,
        status="active",
    )
    p = plan([req], [machine], CENTRES, [], today, DEFAULT_SETTINGS)
    assert len(p.assignments) == 1
    assert p.assignments[0].service_date >= harvest
