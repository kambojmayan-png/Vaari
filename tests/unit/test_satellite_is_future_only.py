"""Satellite sensing is future work only (pilot Part 6)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS = "future (v0.7), not built"


def test_health_reports_satellite_disabled(client):
    assert client.get("/api/health").json()["satellite"] == "disabled"


def test_no_satellite_code_or_libraries():
    banned = re.compile(r"^\s*(import|from)\s+(rasterio|pystac|pystac_client|sentinelhub|ee|earthengine|odc|xarray|stackstac)\b", re.M)
    for path in (ROOT / "app").rglob("*.py"):
        assert not banned.search(path.read_text(encoding="utf-8")), path
    reqs = (ROOT / "requirements.txt").read_text().lower()
    for lib in ("rasterio", "pystac", "sentinelhub", "earthengine", "stackstac"):
        assert lib not in reqs
    assert not (ROOT / "app" / "optional").exists()


def test_docs_agree_on_the_status():
    for name in ("README.md", "docs/ROADMAP.md", "docs/ARCHITECTURE.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert STATUS in text, name
    assert (ROOT / "docs" / "FUTURE_SATELLITE.md").exists()
