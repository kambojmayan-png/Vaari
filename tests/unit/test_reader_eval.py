"""reader-eval: per-field k of N, silent errors, common errors, pass bar (pilot Part 5)."""

import json
import shutil
from pathlib import Path

import pytest

from app.intake import eval as ev
from app.intake.reader import ReaderInfo, RegisterDraft, RowDraft

PAGES = Path(__file__).resolve().parents[2] / "examples" / "register_pages"


class TruthReader:
    """Returns exactly the expected rows of whichever synthetic page it is shown (by order of calls)."""

    info = ReaderInfo(name="custom", kind="custom")

    def __init__(self, pages, tamper=None):
        self.pages = list(pages)
        self.tamper = tamper or (lambda stem, row: row)

    def read(self, image, media_type="image/jpeg"):
        stem, expected = self.pages.pop(0)
        rows = []
        for r in expected["rows"]:
            row = RowDraft(row=r["row"], fields=dict(r["fields"]), confidence=dict.fromkeys(ev.FIELDS, 0.95), issues=[])
            rows.append(self.tamper(stem, row))
        return RegisterDraft(rows=[r for r in rows if r is not None], reader="custom", prompt_version="v2", latency_ms=1)


@pytest.fixture
def synth_dir(tmp_path):
    d = tmp_path / "pages"
    d.mkdir()
    for p in sorted(PAGES.glob("synth_*.expected.json")):
        shutil.copy(p, d / p.name)
        (d / p.name.replace(".expected.json", ".jpg")).write_bytes(ev.TINY_SYNTHETIC_JPEG)
    return d


def expected_pages(d):
    return [(p.name.replace(".expected.json", ""), json.loads(p.read_text(encoding="utf-8"))) for p in sorted(d.glob("*.expected.json"))]


def test_the_committed_set_has_6_pages_and_48_rows():
    pages = sorted(PAGES.glob("synth_*.expected.json"))
    assert len(pages) == 6
    assert sum(len(json.loads(p.read_text(encoding="utf-8"))["rows"]) for p in pages) == ev.PASS_BAR["rows"] == 48


def test_a_perfect_reader_passes(synth_dir):
    body = ev.evaluate_directory(synth_dir, reader=TruthReader(expected_pages(synth_dir)), report_file=None)
    assert "**PASS**" in body
    assert "| phone right | 48 of 48 |" in body
    assert "- none" in body


def test_one_confident_wrong_phone_fails_the_bar(synth_dir):
    def tamper(stem, row):
        if stem == "synth_03" and row.row == 2:
            row.fields["phone"] = "9000003099"  # wrong, but looks sure and passes validation
        return row

    body = ev.evaluate_directory(synth_dir, reader=TruthReader(expected_pages(synth_dir), tamper), report_file=None)
    assert "**FAIL**" in body
    assert "| Silent phone errors | 1 of 48 | 0 of 48 | **no** |" in body
    assert "| phone right | 47 of 48 |" in body  # still above 46, so the silent error alone fails it
    assert "1 × phone:" in body and "→ `9000003002` → `9000003099`" in body


def test_a_wrong_phone_that_is_highlighted_is_not_silent(synth_dir):
    def tamper(stem, row):
        if stem == "synth_03" and row.row == 2:
            row.fields["phone"] = "9000003099"
            row.confidence["phone"] = 0.4  # amber on screen: a person will look
        return row

    body = ev.evaluate_directory(synth_dir, reader=TruthReader(expected_pages(synth_dir), tamper), report_file=None)
    assert "| Silent phone errors | 0 of 48 | 0 of 48 | yes |" in body
    assert "**PASS**" in body


def test_missing_and_invented_rows_are_counted(synth_dir):
    def tamper(stem, row):
        if stem == "synth_01" and row.row == 8:
            return None
        if stem == "synth_02" and row.row == 1:
            row.row = 99
        return row

    body = ev.evaluate_directory(synth_dir, reader=TruthReader(expected_pages(synth_dir), tamper), report_file=None)
    assert "| Rows found | 46 of 48 |" in body and "| Invented rows | 1 |" in body
    assert "(row missing)" in body


def test_a_page_that_fails_to_read_is_reported(synth_dir):
    class Broken:
        info = ReaderInfo(name="custom", kind="custom")

        def read(self, image, media_type="image/jpeg"):
            from app.intake.reader import ReaderUnavailable

            raise ReaderUnavailable("timed out")

    body = ev.evaluate_directory(synth_dir, reader=Broken(), report_file=None)
    assert "ReaderUnavailable: timed out" in body and "**FAIL**" in body


def test_results_replace_only_their_own_section(tmp_path):
    report = tmp_path / "R.md"
    report.write_text("intro\n<!-- results:mock:start -->\nold\n<!-- results:mock:end -->\n"
                      "<!-- results:gemini_demo:start -->\nkeep me\n<!-- results:gemini_demo:end -->\n")
    ev.write_section("mock", "new body", report)
    text = report.read_text(encoding="utf-8")
    assert "new body" in text and "old" not in text and "keep me" in text and text.startswith("intro")


def test_pass_bar_matches_the_document():
    doc = (Path(__file__).resolve().parents[2] / "docs" / "READER_EVAL.md").read_text(encoding="utf-8")
    for line in ("**0 of 48**", "48 of 48, and 0 invented rows", "at least 46 of 48", "at least 45 of 48",
                 "at least 44 of 48", "at least 43 of 48"):
        assert line in doc, line
    assert (ev.PASS_BAR["phone"], ev.PASS_BAR["acres"], ev.PASS_BAR["service_type"],
            ev.PASS_BAR["harvest_date"], ev.PASS_BAR["village"]) == (46, 46, 45, 44, 43)
