"""Seed data generator and database reset for Vaari (Contract Section 12).

40 requests design:
# | id | created offset | type | acres | harvest offset | deadline offset | village | expected outcome
1 | 1 | 08:00 | super_seeder | 3.2 | -2 | 0 | Pind Kalan | Scheduled (Demo: Super Seeder 01, today, seq 1)
2 | 2 | 08:01 | super_seeder | 4.8 | -1 | 0 | Pind Kalan | Scheduled (today, SS 01, 8.0 ac full)
3 | 3 | 08:02 | super_seeder | 4.0 | -1 | 0 | Bhucho Khurd | Scheduled (today, SS 02)
4 | 4 | 08:03 | super_seeder | 4.0 | -1 | 0 | Rampura Phul | Scheduled (today, SS 02, 8.0 ac full)
5 | 5 | 08:04 | super_seeder | 2.5 | -1 | 0 | Kot Shamir | will_miss (NO_CAPACITY, deadline today)
6 | 6 | 08:05 | super_seeder | 3.0 | -1 | 0 | Maur Mandi | will_miss (NO_CAPACITY, deadline today)
7 | 7 | 08:06 | super_seeder | 3.0 | -10 | -1 | Sangat Kalan | will_miss (DEADLINE_PASSED)
8 | 8 | 08:07 | mulcher | 4.0 | 0 | 5 | Talwandi Sabo | will_miss (NO_COMPATIBLE_MACHINE)
9 | 9 | 08:08 | mulcher | 5.0 | 1 | 6 | Goniana Mandi | will_miss (NO_COMPATIBLE_MACHINE)
10 | 10 | 08:09 | baler | 6.0 | 0 | 5 | Pind Kalan | will_miss (MACHINE_UNAVAILABLE)
11 | 11 | 08:10 | super_seeder | 3.0 | 0 | 5 | Tibbi Far | will_miss (TRAVEL_INFEASIBLE)
12..16 | 12..16 | 08:11..15 | various | 2.5..4.0 | None | None | various | needs_info (5 requests)
17..40 | 17..40 | 08:16..39 | seeders/baler | 3.5..10.0 | future | future | various | Scheduled (24 requests)
Total: exactly 28 scheduled, 7 will miss, 5 needs info = 40 requests.
"""

import json
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app import clock
from app.config import settings
from app.db import get_engine, get_session_factory
from app.enums import to_x100
from app.event_log import log_event
from app.models import Centre, Farmer, Machine, Plot, Request, Village
from app.scheduler.dates import compute_dates
from app.scheduler.service import run_for_centre
from app.tokens import driver_link_expiry, new_token


def load_villages(session: Session, centre_lat: float, centre_lon: float) -> dict[str, Village]:
    json_path = Path(__file__).parent / "villages.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))

    villages = {}
    for item in data:
        name = item["name"]
        d_lat = item["offset_km_north"] / 111.0
        d_lon = item["offset_km_east"] / (111.0 * 0.8596)
        lat = round(centre_lat + d_lat, 4)
        lon = round(centre_lon + d_lon, 4)

        v = session.query(Village).filter_by(name=name).first()
        if v is None:
            v = Village(name=name, lat=lat, lon=lon)
            session.add(v)
            session.flush()
        villages[name] = v
    return villages


def seed_data(session: Session) -> dict[str, int]:
    today = clock.today()

    # 1. Centres
    # Home centre
    home = session.query(Centre).filter_by(is_home=True).first()
    if home is None:
        home = Centre(
            name=settings.centre_name,
            phone=settings.centre_phone,
            lat=settings.centre_lat,
            lon=settings.centre_lon,
            is_home=True,
            service_types=["super_seeder", "happy_seeder", "baler"],
        )
        session.add(home)
        session.flush()

    # Centre B (~8 km away)
    cb = session.query(Centre).filter_by(name="Centre B").first()
    if cb is None:
        cb = Centre(
            name="Centre B",
            phone="9876543202",
            lat=round(settings.centre_lat + 8.0 / 111.0, 4),
            lon=round(settings.centre_lon, 4),
            is_home=False,
            service_types=["super_seeder", "mulcher"],
        )
        session.add(cb)

    # Centre C (~15 km away)
    cc = session.query(Centre).filter_by(name="Centre C").first()
    if cc is None:
        cc = Centre(
            name="Centre C",
            phone="9876543203",
            lat=round(settings.centre_lat - 15.0 / 111.0, 4),
            lon=round(settings.centre_lon, 4),
            is_home=False,
            service_types=["baler", "super_seeder"],
        )
        session.add(cc)
    session.flush()

    # 2. Machines (Home centre)
    machines_data = [
        ("Super Seeder 01", "Super Seeder", ["super_seeder"], 8.0, None),
        ("Super Seeder 02", "Super Seeder", ["super_seeder"], 8.0, None),
        ("Baler 01", "Baler", ["baler"], 15.0, today + timedelta(days=10)),
    ]

    for m_name, m_type, stypes, cap, active_from in machines_data:
        m = session.query(Machine).filter_by(centre_id=home.id, name=m_name).first()
        if m is None:
            m = Machine(
                centre_id=home.id,
                name=m_name,
                type=m_type,
                service_types=stypes,
                capacity_acres_x100=to_x100(cap),
                implement_width_m=2.0,
                active_from=active_from,
                active_to=None,
                status="active",
                link_token=new_token(),
                link_expires_at=driver_link_expiry(),
            )
            session.add(m)
    session.flush()

    # 3. Villages
    villages = load_villages(session, home.lat, home.lon)

    # 4. Requests (exactly 40)
    seed_phones = settings.seed_phones
    if not seed_phones:
        seed_phones = [f"900000{i:04d}" for i in range(1, 41)]

    # Exactly 10 farmers with no name: e.g. indices 5, 8, 12, 15, 18, 22, 25, 28, 32, 35
    no_name_indices = {5, 8, 12, 15, 18, 22, 25, 28, 32, 35}
    # Refuse evidence consent for 3 farmers: e.g. indices 7, 14, 21
    no_evidence_consent = {7, 14, 21}

    # Request specs: (type, acres, harvest_offset, deadline_offset, village_name)
    specs = [
        # Demo request (id 1)
        ("super_seeder", 3.2, -2, 0, "Pind Kalan"),
        # Fill today SS01
        ("super_seeder", 4.8, -1, 0, "Pind Kalan"),
        # Fill today SS02 (8.0 acres)
        ("super_seeder", 4.0, -1, 0, "Bhucho Khurd"),
        ("super_seeder", 4.0, -1, 0, "Rampura Phul"),
        # Will-miss: NO_CAPACITY (2 requests)
        ("super_seeder", 2.5, -1, 0, "Kot Shamir"),
        ("super_seeder", 3.0, -1, 0, "Maur Mandi"),
        # Will-miss: DEADLINE_PASSED (1 request)
        ("super_seeder", 3.0, -10, -1, "Sangat Kalan"),
        # Will-miss: NO_COMPATIBLE_MACHINE (2 requests)
        ("mulcher", 4.0, 0, 5, "Talwandi Sabo"),
        ("mulcher", 5.0, 1, 6, "Goniana Mandi"),
        # Will-miss: MACHINE_UNAVAILABLE (1 request)
        ("baler", 6.0, 0, 5, "Pind Kalan"),
        # Will-miss: TRAVEL_INFEASIBLE (1 request)
        ("super_seeder", 3.0, 0, 5, "Tibbi Far"),
        # Needs info (5 requests)
        ("super_seeder", 2.5, None, None, "Pind Kalan"),
        ("super_seeder", 3.0, None, None, "Bhucho Khurd"),
        ("happy_seeder", 4.0, None, None, "Rampura Phul"),
        ("baler", 5.0, None, None, "Kot Shamir"),
        ("super_seeder", 3.5, None, None, "Maur Mandi"),
        # Future scheduled: Day 1 (16 acres)
        ("super_seeder", 4.0, 0, 1, "Pind Kalan"),
        ("super_seeder", 4.0, 0, 1, "Pind Kalan"),
        ("super_seeder", 4.0, 0, 1, "Bhucho Khurd"),
        ("super_seeder", 4.0, 0, 1, "Rampura Phul"),
        # Future scheduled: Day 2 (16 acres)
        ("super_seeder", 4.0, 1, 2, "Kot Shamir"),
        ("super_seeder", 4.0, 1, 2, "Maur Mandi"),
        ("super_seeder", 4.0, 1, 2, "Sangat Kalan"),
        ("super_seeder", 4.0, 1, 2, "Talwandi Sabo"),
        # Future scheduled: Day 3
        ("super_seeder", 5.0, 1, 3, "Goniana Mandi"),
        ("super_seeder", 5.0, 1, 3, "Pind Kalan"),
        # Future scheduled: Day 4
        ("super_seeder", 4.5, 2, 4, "Bhucho Khurd"),
        ("super_seeder", 4.5, 2, 4, "Rampura Phul"),
        # Future scheduled: Day 5
        ("super_seeder", 3.5, 2, 5, "Kot Shamir"),
        ("super_seeder", 3.5, 2, 5, "Maur Mandi"),
        # Future scheduled: Day 6
        ("super_seeder", 4.0, 3, 6, "Sangat Kalan"),
        ("super_seeder", 4.0, 3, 6, "Talwandi Sabo"),
        # Future scheduled: Day 7
        ("super_seeder", 5.0, 4, 7, "Goniana Mandi"),
        ("super_seeder", 5.0, 4, 7, "Pind Kalan"),
        # Future scheduled: Day 8
        ("super_seeder", 4.0, 5, 8, "Bhucho Khurd"),
        ("super_seeder", 4.0, 5, 8, "Rampura Phul"),
        # Future scheduled: Day 9
        ("super_seeder", 4.0, 6, 9, "Kot Shamir"),
        ("super_seeder", 4.0, 6, 9, "Maur Mandi"),
        # Future scheduled: Day 10 (Baler available)
        ("baler", 10.0, 8, 11, "Pind Kalan"),
        ("baler", 5.0, 8, 11, "Bhucho Khurd"),
    ]

    assert len(specs) == 40, f"Expected 40 specs, got {len(specs)}"

    base_time = datetime(today.year, today.month, today.day, 8, 0, 0, tzinfo=timezone.utc)

    for idx, (stype, acres, h_off, d_off, v_name) in enumerate(specs):
        created_at = base_time + timedelta(minutes=idx)
        phone = seed_phones[idx % len(seed_phones)]
        name = None if idx in no_name_indices else f"Farmer {idx + 1}"
        consent_ev = idx not in no_evidence_consent

        # Upsert farmer
        farmer = session.query(Farmer).filter_by(phone=phone).first()
        if farmer is None:
            farmer = Farmer(
                phone=phone,
                name=name,
                language="pa",
                consent_service=True,
                consent_evidence=consent_ev,
                consent_share=True,
                consent_at=created_at,
                consent_simulated=True,
            )
            session.add(farmer)
            session.flush()

        v = villages[v_name]
        # Demo request gets exact pin at centre
        if idx == 0:
            pin_lat = settings.demo_plot_lat
            pin_lon = settings.demo_plot_lon
            loc_src = "pin"
        elif v_name == "Tibbi Far":
            pin_lat = v.lat
            pin_lon = v.lon
            loc_src = "village"
        else:
            pin_lat = v.lat
            pin_lon = v.lon
            loc_src = "village"

        acres_x100 = to_x100(acres)
        plot = Plot(
            farmer_id=farmer.id,
            village_name=v_name,
            village_id=v.id,
            pin_lat=pin_lat,
            pin_lon=pin_lon,
            acres_x100=acres_x100,
            centroid_lat=pin_lat,
            centroid_lon=pin_lon,
            location_source=loc_src,
        )
        session.add(plot)
        session.flush()

        harvest_date = today + timedelta(days=h_off) if h_off is not None else None
        given_deadline = today + timedelta(days=d_off) if d_off is not None else None
        sow_by, deadline_date, deadline_overridden = compute_dates(
            harvest_date=harvest_date,
            service_type=stype,
            given_deadline=given_deadline,
        )
        req_status = "open" if harvest_date is not None else "needs_info"

        req = Request(
            centre_id=home.id,
            farmer_id=farmer.id,
            plot_id=plot.id,
            service_type=stype,
            source="seed",
            acres_x100=acres_x100,
            harvest_date=harvest_date,
            sow_by=sow_by,
            deadline_date=deadline_date,
            deadline_overridden=deadline_overridden,
            status=req_status,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(req)
        session.flush()

        log_event(
            session=session,
            actor="system",
            entity="request",
            entity_id=req.id,
            event="created",
            payload={"source": "seed"},
        )

    session.flush()
    counts = run_for_centre(session, home.id)
    session.commit()
    return counts


def reset_db() -> dict[str, int]:
    t0 = time.perf_counter()
    engine = get_engine()
    engine.dispose()

    # Delete db file and wal files
    db_file = Path(settings.db_path)
    for p in [db_file, Path(f"{db_file}-wal"), Path(f"{db_file}-shm")]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

    # Delete data/photos and data/register_pages
    data_dir = Path(settings.data_dir)
    for sub in ["photos", "register_pages"]:
        target = data_dir / sub
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)

    # Recreate tables with the migrations (pilot B6)
    from app.migrate import ensure_schema

    ensure_schema(get_engine())

    SessionFactory = get_session_factory()
    with SessionFactory() as session:
        counts = seed_data(session)

    elapsed = time.perf_counter() - t0
    print(f"Reset completed in {elapsed:.2f}s:")
    print(f"  Scheduled:  {counts.get('scheduled')}")
    print(f"  Will miss:  {counts.get('will_miss')}")
    print(f"  Needs info: {counts.get('needs_info')}")
    if settings.is_production:
        print("  Sign in:    with a staff account (python tasks.py create-user)")
    else:
        print("  Passcode:   set in .env as VAARI_DEMO_PASSCODE (development only)")

    # Print driver paths
    with SessionFactory() as session:
        machines = session.query(Machine).order_by(Machine.id.asc()).all()
        for m in machines:
            print(f"  Driver {m.name}: /driver/{m.link_token}")

    return counts


if __name__ == "__main__":
    if settings.is_production and "--yes-delete-everything" not in sys.argv:
        # Reset deletes the database and every photo; seeding adds fictional farmers.
        print("Refused: reset and seed are for development. In production they would delete or mix in demo data.")
        print("If you really mean it, add --yes-delete-everything.")
        sys.exit(1)
    if "--reset" in sys.argv:
        reset_db()
    else:
        from app.migrate import ensure_schema

        ensure_schema()
        sf = get_session_factory()
        with sf() as s:
            counts = seed_data(s)
            print(f"Seed completed: {counts}")
