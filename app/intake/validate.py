"""Deterministic validation and normalization of register draft rows (Step 02)."""

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

LOW_CONFIDENCE_THRESHOLD: float = 0.8
FAILING_CONFIDENCE_CAP: float = 0.3

PHONE_RE = re.compile(r"^[6-9]\d{9}$")

VALID_SERVICE_TYPES = {"super_seeder", "happy_seeder", "baler", "mulcher"}

SERVICE_TYPE_MAP: dict[str, str] = {
    # Super Seeder
    "super_seeder": "super_seeder",
    "super seeder": "super_seeder",
    "superseeder": "super_seeder",
    "ss": "super_seeder",
    "s.s.": "super_seeder",
    "ਸੁਪਰ ਸੀਡਰ": "super_seeder",
    "ਸੁਪਰ": "super_seeder",
    # Happy Seeder
    "happy_seeder": "happy_seeder",
    "happy seeder": "happy_seeder",
    "happyseeder": "happy_seeder",
    "hs": "happy_seeder",
    "h.s.": "happy_seeder",
    "ਹੈਪੀ ਸੀਡਰ": "happy_seeder",
    "ਹੈਪੀ": "happy_seeder",
    # Baler
    "baler": "baler",
    "ਬੇਲਰ": "baler",
    # Mulcher
    "mulcher": "mulcher",
    "ਮਲਚਰ": "mulcher",
}

from app.intake.normalize import (  # noqa: E402  (kept beside the old helpers it replaces)
    month_name_date,
    normalize_phone,
    normalize_service,
    parse_acres,
    to_ascii_digits,
)

# Issues that ask a person to look but do not stop the row being confirmed.
WARNING_PREFIXES = (
    "acres: unusually large, check the register",
    "acres: converted from",
)


def _normalize_digits(text: str) -> str:
    return to_ascii_digits(text)


def _parse_harvest_date(raw_val: Any, today: date) -> tuple[str | None, str | None]:
    """Parse harvest date accepting YYYY-MM-DD, DD-MM-YYYY, or DD/MM (assuming season year).

    Returns (normalized_iso_or_original, error_message_or_none).
    """
    if raw_val is None:
        return None, None
    s = _normalize_digits(str(raw_val).strip())
    if not s:
        return None, None

    parsed: date | None = None

    # 1. Try YYYY-MM-DD
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$", s):
        try:
            parts = [int(p) for p in s.split("-")]
            parsed = date(parts[0], parts[1], parts[2])
        except ValueError:
            return s, "harvest_date: invalid calendar date"

    # 2. Try DD-MM-YYYY or DD/MM/YYYY
    elif re.match(r"^\d{1,2}[-/]\d{1,2}[-/]\d{4}$", s):
        sep = "-" if "-" in s else "/"
        try:
            d_part, m_part, y_part = [int(p) for p in s.split(sep)]
            parsed = date(y_part, m_part, d_part)
        except ValueError:
            return s, "harvest_date: invalid calendar date"

    # 2b. Try DD-MM-YY, DD/MM/YY, DD.MM.YY (or YY-MM-DD)
    elif re.match(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{2}$", s):
        try:
            p1, p2, p3 = [int(p) for p in re.split(r"[-/.]", s)]
            if p1 == (today.year % 100) and p3 <= 31:
                parsed = date(2000 + p1, p2, p3)
            else:
                parsed = date(2000 + p3, p2, p1)
        except ValueError:
            return s, "harvest_date: invalid calendar date"

    # 3. Try DD/MM or DD-MM (assume current season's year: today.year)
    elif re.match(r"^\d{1,2}[/-]\d{1,2}$", s):
        sep = "/" if "/" in s else "-"
        try:
            d_part, m_part = [int(p) for p in s.split(sep)]
            parsed = date(today.year, m_part, d_part)
        except ValueError:
            return s, "harvest_date: invalid calendar date"
    else:
        named = month_name_date(s)
        if named is None:
            return s, "harvest_date: invalid date format"
        d_part, m_part, y_part = named
        try:
            parsed = date(y_part or today.year, m_part, d_part)
        except ValueError:
            return s, "harvest_date: invalid calendar date"

    min_date = today - timedelta(days=30)
    max_date = today + timedelta(days=60)
    if parsed < min_date or parsed > max_date:
        return (
            parsed.isoformat(),
            f"harvest_date: must be between {min_date.isoformat()} and {max_date.isoformat()}",
        )

    return parsed.isoformat(), None


def validate_row(
    fields: dict[str, Any],
    today: date,
    confidence: dict[str, float] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Deterministically validate a drafted row without dropping any failing cell.

    If `confidence` dict is passed, any field with an issue has its confidence capped at 0.3 in-place.
    Returns (clean_fields, issues).
    """
    clean: dict[str, Any] = {
        "phone": fields.get("phone"),
        "name": fields.get("name"),
        "village": fields.get("village"),
        "acres": fields.get("acres"),
        "service_type": fields.get("service_type"),
        "harvest_date": fields.get("harvest_date"),
        "note": fields.get("note"),
    }
    issues: list[str] = []

    def record_issue(field_name: str, msg: str) -> None:
        issues.append(msg)
        if confidence is not None:
            cur = confidence.get(field_name, FAILING_CONFIDENCE_CAP)
            confidence[field_name] = min(float(cur), FAILING_CONFIDENCE_CAP)

    # 1. Phone: required, 10 digits starting 6 to 9
    raw_phone = clean.get("phone")
    if raw_phone is None or str(raw_phone).strip() == "":
        clean["phone"] = raw_phone
        record_issue("phone", "phone: missing")
    else:
        norm_phone = normalize_phone(str(raw_phone).strip())
        clean["phone"] = norm_phone
        if not PHONE_RE.match(norm_phone):
            record_issue("phone", "phone: must be 10 digits starting with 6-9")

    # 2. Name: optional
    raw_name = clean.get("name")
    if raw_name is not None:
        s_name = str(raw_name).strip()
        clean["name"] = s_name if s_name else None

    # 3. Village: required
    raw_village = clean.get("village")
    if raw_village is None or not str(raw_village).strip():
        clean["village"] = raw_village
        record_issue("village", "village: missing")
    else:
        clean["village"] = str(raw_village).strip()

    # 4. Acres: required, 0.25 to 200, at most 2 decimals; > 25 warning
    raw_acres = clean.get("acres")
    if raw_acres is None or (isinstance(raw_acres, str) and not raw_acres.strip()):
        clean["acres"] = raw_acres
        record_issue("acres", "acres: missing")
    else:
        try:
            parsed_acres, acres_warning = parse_acres(raw_acres)
            s_acres = parsed_acres if parsed_acres is not None else _normalize_digits(str(raw_acres).strip())
            if acres_warning:
                record_issue("acres", acres_warning)
            d_acres = Decimal(s_acres)
            f_acres = float(d_acres)
            clean["acres"] = f_acres
            if d_acres.as_tuple().exponent < -2:
                record_issue("acres", "acres: at most 2 decimal places allowed")
            elif f_acres < 0.25 or f_acres > 200.0:
                record_issue("acres", "acres: must be between 0.25 and 200")
            elif f_acres > 25.0:
                record_issue("acres", "acres: unusually large, check the register")
        except Exception:
            clean["acres"] = raw_acres
            record_issue("acres", "acres: must be a number between 0.25 and 200")

    # 5. Service type: required, accepts English, abbreviations, and Punjabi Gurmukhi
    raw_st = clean.get("service_type")
    if raw_st is None or not str(raw_st).strip():
        clean["service_type"] = raw_st
        record_issue("service_type", "service_type: missing")
    else:
        key = str(raw_st).strip().lower()
        mapped = (
            SERVICE_TYPE_MAP.get(key)
            or SERVICE_TYPE_MAP.get(str(raw_st).strip())
            or normalize_service(raw_st)
        )
        if mapped in VALID_SERVICE_TYPES:
            clean["service_type"] = mapped
        else:
            clean["service_type"] = raw_st
            record_issue("service_type", f"service_type: unknown service '{raw_st}'")

    # 6. Harvest date: optional, accepts 18/10, 18-10-2026, 2026-10-18 within [today-30d, today+60d]
    raw_hd = clean.get("harvest_date")
    norm_hd, hd_err = _parse_harvest_date(raw_hd, today)
    clean["harvest_date"] = norm_hd
    if hd_err:
        record_issue("harvest_date", hd_err)

    # 7. Note: optional
    raw_note = clean.get("note")
    if raw_note is not None:
        s_note = str(raw_note).strip()
        clean["note"] = s_note if s_note else None

    return clean, issues


def is_warning(issue: str) -> bool:
    return issue.startswith(WARNING_PREFIXES)


def has_blocking_issues(issues: list[str]) -> bool:
    """Return True if any issue is a blocking validation error (warnings such as >25 acres are not)."""
    return any(not is_warning(iss) for iss in issues)
