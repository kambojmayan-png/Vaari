"""Clock and date helpers for Vaari.

The ONLY place in app/ that reads the system clock or date.
"""

import time
import zoneinfo
from datetime import date, datetime, timezone

from app.config import settings

_PUNJABI_MONTHS = {
    1: "ਜਨਵਰੀ",
    2: "ਫ਼ਰਵਰੀ",
    3: "ਮਾਰਚ",
    4: "ਅਪ੍ਰੈਲ",
    5: "ਮਈ",
    6: "ਜੂਨ",
    7: "ਜੁਲਾਈ",
    8: "ਅਗਸਤ",
    9: "ਸਤੰਬਰ",
    10: "ਅਕਤੂਬਰ",
    11: "ਨਵੰਬਰ",
    12: "ਦਸੰਬਰ",
}

_ENGLISH_MONTHS = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


def now_utc() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def monotonic() -> float:
    """Seconds from a monotonic clock, for rate limits and timers (never for dates)."""
    return time.monotonic()


def today() -> date:
    """Return today's date. Uses VAARI_TODAY if set, else current date in VAARI_TZ."""
    override = settings.today
    if override:
        return date.fromisoformat(override)
    tz = zoneinfo.ZoneInfo(settings.tz)
    return now_utc().astimezone(tz).date()


def ist_date(dt_utc: datetime) -> date:
    """Return the date in Asia/Kolkata for a given UTC datetime."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    return dt_utc.astimezone(tz).date()


def fmt_en(d: date) -> str:
    """Format date in English, e.g. '23 Oct'."""
    return f"{d.day} {_ENGLISH_MONTHS[d.month]}"


def fmt_pa(d: date) -> str:
    """Format date in Punjabi, e.g. '23 ਅਕਤੂਬਰ'."""
    return f"{d.day} {_PUNJABI_MONTHS[d.month]}"


def iso_z(dt: datetime) -> str:
    """Format datetime as UTC ISO 8601 with trailing Z, e.g. '2026-10-23T05:42:10Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
