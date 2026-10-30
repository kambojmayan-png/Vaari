"""Reader evaluation (`python tasks.py reader-eval`), pilot Part 5.

Runs the configured reader on every page in examples/register_pages/ that has
a `<stem>.expected.json`, through the same path as a real upload (clean the
image, preprocess it, read it, validate every cell). It scores each field on
each page as *k of N*, counts silent errors (a wrong phone or acres value
shown with confidence >= 0.8 and no validation issue), lists the most common
errors, checks the pass bar in docs/READER_EVAL.md, prints the report and
writes it into that file's section for this reader.

Counts, never percentages: the set is small.
"""

import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
PAGES_DIR = ROOT_DIR / "examples" / "register_pages"
REPORT_FILE = ROOT_DIR / "docs" / "READER_EVAL.md"

FIELDS = ("phone", "acres", "service_type", "harvest_date", "village", "name")
SILENT_FIELDS = ("phone", "acres")
SURE = 0.8  # confidence at or above this is shown without highlighting

# The pass bar, as written in docs/READER_EVAL.md (decided before any run). Over the synth_* set.
PASS_BAR = {
    "rows": 48,
    "silent_phone": 0,
    "silent_acres": 0,
    "invented_rows": 0,
    "phone": 46,
    "acres": 46,
    "service_type": 45,
    "harvest_date": 44,
    "village": 43,
}
BAR_SET_PREFIX = "synth_"

TINY_SYNTHETIC_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00"
    b"\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19"
    b"\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05"
    b"\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06"
    b"\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
)


def ensure_sample_pages(pages_dir: Path = PAGES_DIR) -> None:
    """Draw the synthetic pages if missing; give page1 its 1-pixel placeholder image."""
    pages_dir.mkdir(parents=True, exist_ok=True)
    if pages_dir == PAGES_DIR and not all((pages_dir / f"synth_{i:02d}.jpg").exists() for i in range(1, 7)):
        sys.path.insert(0, str(ROOT_DIR / "scripts"))
        from make_synthetic_register_pages import generate

        generate(pages_dir)
    p1 = pages_dir / "page1.jpg"
    if (pages_dir / "page1.expected.json").exists() and not p1.exists():
        p1.write_bytes(TINY_SYNTHETIC_JPEG)


def _norm(field_name: str, val: Any) -> str:
    if val is None or (isinstance(val, str) and not val.strip()):
        return ""
    if field_name == "acres":
        try:
            return f"{float(val):g}"
        except (TypeError, ValueError):
            return str(val).strip().lower()
    return " ".join(str(val).split()).lower()


@dataclass
class PageScore:
    stem: str
    rows_expected: int = 0
    rows_found: int = 0
    invented_rows: int = 0
    right: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    silent: dict[str, int] = field(default_factory=lambda: dict.fromkeys(SILENT_FIELDS, 0))
    seconds: float = 0.0
    error: str | None = None
    errors: list[tuple[str, str, str, str]] = field(default_factory=list)  # field, written, expected, got


def score_page(stem: str, expected_rows: list[dict], draft_rows: list | None, seconds: float, error: str | None = None) -> PageScore:
    ps = PageScore(stem=stem, rows_expected=len(expected_rows), seconds=seconds, error=error)
    got = {r.row: r for r in (draft_rows or [])}
    expected_nos = set()
    for idx, exp in enumerate(expected_rows, start=1):
        r_no = int(exp.get("row", idx))
        expected_nos.add(r_no)
        exp_fields = exp.get("fields", exp)
        written = exp.get("written", {})
        act = got.get(r_no)
        if act is None:
            for f in FIELDS:
                ps.errors.append((f, str(written.get(f, "")), _norm(f, exp_fields.get(f)), "(row missing)"))
            continue
        ps.rows_found += 1
        for f in FIELDS:
            e, a = _norm(f, exp_fields.get(f)), _norm(f, act.fields.get(f))
            if e == a:
                ps.right[f] += 1
                continue
            ps.errors.append((f, str(written.get(f, "")), e or "(blank)", a or "(blank)"))
            if f in SILENT_FIELDS:
                conf = float(act.confidence.get(f, 0.0))
                flagged = any(i.startswith(f"{f}:") for i in act.issues)
                if conf >= SURE and not flagged:
                    ps.silent[f] += 1
    ps.invented_rows = len(set(got) - expected_nos)
    return ps


def read_page(reader, image: bytes) -> tuple[list, float, str | None]:
    """The real upload path: clean, preprocess, read."""
    from app.intake.preprocess import preprocess_for_reader
    from app.storage.sanitize import sanitize_image

    t0 = time.perf_counter()
    try:
        clean = sanitize_image(image)
        prepared, _ = preprocess_for_reader(clean)
        draft = reader.read(prepared, media_type="image/jpeg")
        return draft.rows, time.perf_counter() - t0, None
    except Exception as exc:
        return [], time.perf_counter() - t0, f"{type(exc).__name__}: {str(exc)[:120]}"


def bar_check(scores: list[PageScore]) -> tuple[bool, list[tuple[str, str, str, bool]]]:
    """Apply PASS_BAR to the synth_* pages. Returns (passed, [(check, result, bar, ok)])."""
    bar_pages = [s for s in scores if s.stem.startswith(BAR_SET_PREFIX)]
    n = sum(s.rows_expected for s in bar_pages)
    found = sum(s.rows_found for s in bar_pages)
    invented = sum(s.invented_rows for s in bar_pages)
    lines = []

    def add(check, value, bar_text, ok):
        lines.append((check, value, bar_text, ok))

    add("Rows found", f"{found} of {n}", f"{PASS_BAR['rows']} of {PASS_BAR['rows']}", n == PASS_BAR["rows"] and found == n)
    add("Invented rows", str(invented), "0", invented == PASS_BAR["invented_rows"])
    for f in SILENT_FIELDS:
        silent = sum(s.silent[f] for s in bar_pages)
        add(f"Silent {f} errors", f"{silent} of {n}", f"0 of {n}", silent == PASS_BAR[f"silent_{f}"])
    for f in ("phone", "acres", "service_type", "harvest_date", "village"):
        right = sum(s.right[f] for s in bar_pages)
        add(f"{f} right", f"{right} of {n}", f"at least {PASS_BAR[f]} of {PASS_BAR['rows']}", right >= PASS_BAR[f])
    name_right = sum(s.right["name"] for s in bar_pages)
    add("name right", f"{name_right} of {n}", "reported only", True)
    return all(ok for *_, ok in lines) and bool(bar_pages), lines


def render(reader_label: str, scores: list[PageScore], when: str) -> str:
    passed, lines = bar_check(scores)
    out = [
        f"### {reader_label}",
        "",
        f"Run {when}. Verdict against the pass bar: **{'PASS' if passed else 'FAIL'}**.",
        "",
        "| Check (synth_01 to synth_06) | Result | Bar | Met |",
        "| --- | --- | --- | --- |",
    ]
    out += [f"| {c} | {v} | {b} | {'yes' if ok else '**no**'} |" for c, v, b, ok in lines]
    out += [
        "",
        "Per page (k of N rows right for each field):",
        "",
        "| Page | Rows found | Phone | Acres | Machine | Date | Village | Name | Silent phone | Silent acres | Seconds | Error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in scores:
        n = s.rows_expected
        cells = " | ".join(f"{s.right[f]} of {n}" for f in FIELDS)
        out.append(
            f"| {s.stem} | {s.rows_found} of {n} | {cells} | {s.silent['phone']} | {s.silent['acres']} | "
            f"{s.seconds:.2f} | {s.error or ''} |"
        )
    common = Counter((f, w, e, g) for s in scores for (f, w, e, g) in s.errors)
    out += ["", "Most common errors (field: written on the page → expected → read):", ""]
    if not common:
        out.append("- none")
    for (f, w, e, g), count in common.most_common(10):
        out.append(f"- {count} × {f}: `{w or '(blank)'}` → `{e}` → `{g}`")
    out.append("")
    return "\n".join(out)


def write_section(reader_name: str, body: str, report_file: Path = REPORT_FILE) -> None:
    start, end = f"<!-- results:{reader_name}:start -->", f"<!-- results:{reader_name}:end -->"
    text = report_file.read_text(encoding="utf-8")
    if start not in text or end not in text:
        text = text.rstrip() + f"\n\n{start}\n{end}\n"
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
    report_file.write_text(f"{before}{start}\n{body}\n{end}{after}", encoding="utf-8")


def evaluate_directory(pages_dir: Path | None = None, reader=None, report_file: Path | None = REPORT_FILE) -> str:
    from app import clock
    from app.config import settings
    from app.intake.reader import describe_reader, get_reader, reader_name

    target_dir = pages_dir or PAGES_DIR
    ensure_sample_pages(target_dir)
    name = reader_name(settings) if reader is None else getattr(getattr(reader, "info", None), "name", "custom")
    reader = reader or get_reader(settings)
    info = describe_reader(settings) if name == reader_name(settings) else None

    scores: list[PageScore] = []
    old_today = os.environ.get("VAARI_TODAY")
    try:
        for exp_path in sorted(target_dir.glob("*.expected.json")):
            stem = exp_path.name.replace(".expected.json", "")
            img = next((target_dir / f"{stem}{ext}" for ext in (".jpg", ".jpeg", ".png") if (target_dir / f"{stem}{ext}").exists()), None)
            if img is None:
                continue
            expected = json.loads(exp_path.read_text(encoding="utf-8"))
            # Validate dates as on the day the set was made, so the window check does not drift.
            os.environ["VAARI_TODAY"] = expected.get("anchor_today", "2026-10-25")
            rows, secs, err = read_page(reader, img.read_bytes())
            scores.append(score_page(stem, expected.get("rows", []), rows, secs, err))
    finally:
        if old_today is None:
            os.environ.pop("VAARI_TODAY", None)
        else:
            os.environ["VAARI_TODAY"] = old_today

    label = name
    if info is not None and info.model:
        label += f" ({info.provider}, model {info.model})"
    elif info is not None and info.provider:
        label += f" ({info.provider})"
    body = render(label, scores, clock.iso_z(clock.now_utc()))
    if name == "mock":
        body += (
            "\nThe mock is not a reader: it returns the same six fixture rows for every image, so it is "
            "expected to fail on the synthetic set. It scores on `page1` because that fixture is page1. "
            "This run checks that the evaluation itself works, including counting silent errors.\n"
        )
    print(body)
    if report_file is not None:
        write_section(name, body, report_file)
    return body


if __name__ == "__main__":
    evaluate_directory()
