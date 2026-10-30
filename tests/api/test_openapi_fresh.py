"""Regression test: docs/openapi.json must match the live app schema.

Run automatically with `python tasks.py test`. If this test fails it means
someone changed a route or schema without regenerating the committed file.
Regenerate with:
    python -c "
from app.main import app; import json, pathlib
pathlib.Path('docs/openapi.json').write_bytes(
    (json.dumps(app.openapi(), indent=2, ensure_ascii=False) + '\n')
    .encode('utf-8').replace(b'\r\n', b'\n')
)
"
"""
import json
import pathlib

import pytest

SCHEMA_FILE = pathlib.Path(__file__).parent.parent.parent / "docs" / "openapi.json"

# Number of paths the spec MUST have (update only when routes are intentionally added).
EXPECTED_PATH_COUNT = 33


def test_openapi_json_exists():
    assert SCHEMA_FILE.is_file(), "docs/openapi.json is missing"


def test_openapi_json_lf_only():
    raw = SCHEMA_FILE.read_bytes()
    assert b"\r\n" not in raw, "docs/openapi.json contains CRLF line endings; regenerate with LF"


def test_openapi_json_path_count():
    data = json.loads(SCHEMA_FILE.read_bytes())
    assert len(data["paths"]) == EXPECTED_PATH_COUNT, (
        f"docs/openapi.json has {len(data['paths'])} paths, expected {EXPECTED_PATH_COUNT}"
    )


def test_openapi_json_matches_live_app():
    """Fail if committed openapi.json diverges from what the running app produces.

    Comparison is on parsed JSON dicts (key-order independent) so serialisation
    differences do not cause false failures.

    NOTE: test_errors.py adds a /api/test-protected route at import time, which
    would change the path count.  We compare against the committed schema which
    reflects the *production* routes only. The EXPECTED_PATH_COUNT guard above
    will catch any accidental route additions.  This test validates the schema
    body matches by temporarily resetting the openapi_schema cache so it is
    recomputed from the current route list.
    """
    from app.main import app  # noqa: PLC0415

    # Remember and clear the cached schema so it is recomputed fresh.
    original_schema = app.openapi_schema
    app.openapi_schema = None
    try:
        live_data = app.openapi()
    finally:
        # Restore whatever was cached before this test ran.
        app.openapi_schema = original_schema

    committed_data = json.loads(SCHEMA_FILE.read_bytes())

    # Remove any test-only routes that other test modules register on the live app.
    test_only_prefixes = ("/api/test-",)
    live_paths = {
        k: v for k, v in live_data.get("paths", {}).items()
        if not any(k.startswith(p) for p in test_only_prefixes)
    }
    live_data_filtered = dict(live_data, paths=live_paths)

    if live_data_filtered != committed_data:
        added = set(live_paths) - set(committed_data.get("paths", {}))
        removed = set(committed_data.get("paths", {})) - set(live_paths)
        details = []
        if added:
            details.append(f"Paths in live app but NOT in file: {sorted(added)}")
        if removed:
            details.append(f"Paths in file but NOT in live app: {sorted(removed)}")
        details.append(
            "Re-generate: python -c \"from app.main import app; import json,pathlib; "
            "pathlib.Path('docs/openapi.json').write_bytes("
            "(json.dumps(app.openapi(),indent=2,ensure_ascii=False)+'\\n').encode().replace(b'\\r\\n',b'\\n'))\""
        )
        pytest.fail("docs/openapi.json is out of date with the live app.\n" + "\n".join(details))
