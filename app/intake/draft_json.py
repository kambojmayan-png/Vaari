"""Turning a reader's JSON answer into a validated draft (shared by gemini_demo and custom).

Both remote readers must answer with the same JSON::

    {"rows": [{"row": 1, "fields": {...}, "confidence": {...}}]}

Every value is then checked by ``validate_row``; a cell that fails has its
confidence capped at 0.3, so the confirmation screen highlights it.
"""

import json
import re
from datetime import date
from typing import Any

from app.intake.reader import CORE_FIELDS, RegisterDraft, RowDraft
from app.intake.validate import FAILING_CONFIDENCE_CAP, validate_row

ALLOWED_FIELDS = (*CORE_FIELDS, "note")


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_rows(raw_text: str) -> list[dict[str, Any]]:
    """Parse the reader's answer and enforce the strict schema. Raises ValueError with the first problem.

    Strict means: a top-level object with a ``rows`` list; each row an object with
    ``row`` (a positive integer), ``fields`` (only the known keys, each a string,
    a number or null) and ``confidence`` (a number from 0 to 1 for **every** one of
    phone, name, village, acres, service_type and harvest_date, blank cells
    included). Anything else is refused, and the hosted reader retries once.
    """
    if not raw_text or not isinstance(raw_text, str):
        raise ValueError("Empty response from the reader.")
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    data = json.loads(cleaned)
    if not isinstance(data, dict) or "rows" not in data or not isinstance(data["rows"], list):
        raise ValueError("JSON does not match schema: missing 'rows' list.")

    rows = data["rows"]
    seen: set[int] = set()
    for n, item in enumerate(rows, start=1):
        if not isinstance(item, dict) or "fields" not in item or not isinstance(item["fields"], dict):
            raise ValueError("Each row in 'rows' must be an object containing 'fields'.")
        row_no = item.get("row", n)
        if not isinstance(row_no, int) or isinstance(row_no, bool) or row_no < 1 or row_no in seen:
            raise ValueError(f"Row {n}: 'row' must be a positive whole number, used once.")
        seen.add(row_no)
        extra = set(item["fields"]) - set(ALLOWED_FIELDS)
        if extra:
            raise ValueError(f"Row {row_no}: unknown fields {sorted(extra)}.")
        for k, v in item["fields"].items():
            if v is not None and not isinstance(v, str) and not _is_number(v):
                raise ValueError(f"Row {row_no}: field '{k}' must be text, a number or null.")
        conf = item.get("confidence")
        if not isinstance(conf, dict):
            raise ValueError(f"Row {row_no}: 'confidence' object is missing.")
        for k in CORE_FIELDS:
            v = conf.get(k)
            if not _is_number(v) or not 0.0 <= float(v) <= 1.0:
                raise ValueError(f"Row {row_no}: confidence for '{k}' must be a number from 0 to 1.")
    return rows


def build_draft(
    raw_rows: list[dict[str, Any]],
    today: date,
    reader: str,
    prompt_version: str,
    latency_ms: int,
) -> RegisterDraft:
    rows: list[RowDraft] = []
    for idx, item in enumerate(raw_rows, start=1):
        row_no = int(item.get("row") or idx)
        raw_fields = dict(item.get("fields") or {})
        raw_conf = {
            k: float(v)
            for k, v in (item.get("confidence") or {}).items()
            if v is not None
        }
        clean_fields, issues = validate_row(raw_fields, today, confidence=raw_conf)
        for k in CORE_FIELDS:
            raw_conf.setdefault(k, 0.85 if clean_fields.get(k) is not None else FAILING_CONFIDENCE_CAP)
        rows.append(RowDraft(row=row_no, fields=clean_fields, confidence=raw_conf, issues=issues))
    return RegisterDraft(rows=rows, reader=reader, prompt_version=prompt_version, latency_ms=latency_ms)
