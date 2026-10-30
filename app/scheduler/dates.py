"""Date computation helpers for sowing windows and deadlines."""

from datetime import date, timedelta

from app.config import settings
from app.enums import ServiceType, buffer_days
from app.errors import VaariError


def compute_dates(
    harvest_date: date | None,
    service_type: ServiceType | str,
    given_deadline: date | None = None,
) -> tuple[date | None, date | None, bool]:
    """Compute (sow_by, deadline_date, deadline_overridden).

    Raises VaariError(VALIDATION_ERROR, field="deadline_date") if deadline < harvest.
    """
    if harvest_date is None:
        return None, None, False

    sow_by = harvest_date + timedelta(days=settings.window_days)
    if given_deadline is not None:
        if given_deadline < harvest_date:
            raise VaariError(
                error_code="VALIDATION_ERROR",
                message="Deadline date cannot be before harvest date.",
                http_status=422,
                details={"field": "deadline_date"},
            )
        return sow_by, given_deadline, True

    b_days = buffer_days(service_type)
    deadline_date = sow_by - timedelta(days=b_days)
    return sow_by, deadline_date, False
