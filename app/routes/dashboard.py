"""Dashboard summary and usage CSV API routes (Contract Section 11 & Step 07 / Step 10)."""

import csv
import io
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import clock
from app.auth import Principal, require_staff
from app.db import get_db
from app.enums import from_x100
from app.models import Machine, Plot, Request, ServiceRecord, Slot

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def get_dashboard_summary(
    village: str | None = Query(None),
    date: date | None = Query(None),
    machine_id: int | None = Query(None),
    status: str | None = Query(None),
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_staff),
) -> dict[str, Any]:
    today = clock.today()

    req_query = session.query(Request)
    if village:
        req_query = req_query.join(Plot, Request.plot_id == Plot.id).filter(
            Plot.village_name == village
        )
    if status:
        req_query = req_query.filter(Request.status == status)

    all_requests = req_query.all()
    total_reqs = len(all_requests)

    needs_info_count = sum(1 for r in all_requests if r.status == "needs_info")
    will_miss_count = sum(1 for r in all_requests if r.status == "will_miss")

    by_reason: dict[str, int] = {}
    for r in all_requests:
        if r.status == "will_miss" and r.reason_code:
            by_reason[r.reason_code] = by_reason.get(r.reason_code, 0) + 1

    by_village: dict[str, int] = {}
    for r in all_requests:
        p = session.query(Plot).filter_by(id=r.plot_id).first()
        v_name = p.village_name if p else "Unknown"
        by_village[v_name] = by_village.get(v_name, 0) + 1

    slot_query = session.query(Slot)
    if date:
        slot_query = slot_query.filter(Slot.service_date == date)
    if machine_id:
        slot_query = slot_query.filter(Slot.machine_id == machine_id)
    if village:
        slot_query = (
            slot_query.join(Request, Slot.request_id == Request.id)
            .join(Plot, Request.plot_id == Plot.id)
            .filter(Plot.village_name == village)
        )

    all_slots = slot_query.order_by(Slot.id.asc()).all()
    scheduled_count = sum(1 for s in all_slots if s.status == "scheduled")
    in_progress_count = sum(1 for s in all_slots if s.status == "in_progress")
    completed_count = sum(1 for s in all_slots if s.status == "done")
    needs_review_count = sum(1 for s in all_slots if s.needs_review)

    # Anonymized flagged jobs list for Officer review (no farmer names or phones)
    flagged_jobs: list[dict[str, Any]] = []
    for s in all_slots:
        if s.needs_review:
            r = session.query(Request).filter_by(id=s.request_id).first()
            p = session.query(Plot).filter_by(id=r.plot_id).first() if r else None
            m = session.query(Machine).filter_by(id=s.machine_id).first()
            rec = session.query(ServiceRecord).filter_by(slot_id=s.id).first()
            flagged_jobs.append(
                {
                    "slot_id": s.id,
                    "request_id": f"VR-{r.id}" if r else f"VR-{s.request_id}",
                    "village": p.village_name if p else "Unknown",
                    "machine": m.name if m else "Unknown",
                    "acres": from_x100(r.acres_x100) if r else 0.0,
                    "service_date": str(s.service_date),
                    "flags": s.flags_json or [],
                    "record_token": rec.token if rec else None,
                }
            )

    active_machines = session.query(Machine).filter_by(status="active").all()
    seven_days = [today + timedelta(days=i) for i in range(7)]

    total_cap_x100 = 0
    for m in active_machines:
        for d in seven_days:
            if (m.active_from is None or d >= m.active_from) and (
                m.active_to is None or d <= m.active_to
            ):
                total_cap_x100 += m.capacity_acres_x100

    seven_day_slots = (
        session.query(Slot)
        .filter(
            Slot.service_date >= today,
            Slot.service_date <= today + timedelta(days=6),
            Slot.status.in_(["scheduled", "in_progress", "done"]),
        )
        .all()
    )

    used_cap_x100 = 0
    for s in seven_day_slots:
        r = session.query(Request).filter_by(id=s.request_id).first()
        if r:
            used_cap_x100 += r.acres_x100

    if total_cap_x100 > 0:
        capacity_used_pct = round(100.0 * used_cap_x100 / total_cap_x100)
    else:
        capacity_used_pct = 0

    return {
        "total": total_reqs,
        "needs_info": needs_info_count,
        "scheduled": scheduled_count,
        "in_progress": in_progress_count,
        "completed": completed_count,
        "will_miss": will_miss_count,
        "needs_review": needs_review_count,
        "capacity_used_pct": capacity_used_pct,
        "by_reason": by_reason,
        "by_village": by_village,
        "today": today.isoformat(),
        "flagged_jobs": flagged_jobs,
    }


@router.get("/usage.csv")
def get_usage_csv(
    session: Session = Depends(get_db),
    _principal: Principal = Depends(require_staff),
):
    """Export acres per machine per day as CSV: date,machine,jobs,acres (Contract Section 11)."""
    slots = (
        session.query(Slot)
        .filter(Slot.status.in_(["scheduled", "in_progress", "done"]))
        .order_by(Slot.service_date.asc(), Slot.machine_id.asc(), Slot.seq.asc())
        .all()
    )

    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for s in slots:
        m = session.query(Machine).filter_by(id=s.machine_id).first()
        r = session.query(Request).filter_by(id=s.request_id).first()
        m_name = m.name if m else f"Machine {s.machine_id}"
        key = (str(s.service_date), s.machine_id)
        if key not in grouped:
            grouped[key] = {
                "date": str(s.service_date),
                "machine": m_name,
                "jobs": 0,
                "acres_x100": 0,
            }
        grouped[key]["jobs"] += 1
        grouped[key]["acres_x100"] += r.acres_x100 if r else 0

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "machine", "jobs", "acres"])
    for item in grouped.values():
        writer.writerow(
            [
                item["date"],
                item["machine"],
                item["jobs"],
                from_x100(item["acres_x100"]),
            ]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="vaari_usage.csv"'},
    )
