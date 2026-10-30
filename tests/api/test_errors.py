"""Error handling and auth API tests."""

from fastapi import Depends

from app.auth import require_passcode
from app.main import app


# Add a test-only route for checking passcode protection
@app.get("/api/test-protected")
def dummy_protected(_passcode: str = Depends(require_passcode)):
    return {"status": "ok"}


def test_unknown_api_route_returns_not_found_error_shape(client):
    response = client.get("/api/non-existent-route")
    assert response.status_code == 404
    assert "application/json" in response.headers.get("content-type", "")
    data = response.json()
    assert data["error_code"] == "NOT_FOUND"
    assert "message" in data
    assert "details" in data


def test_protected_route_without_passcode_returns_401(client):
    response = client.get("/api/test-protected")
    assert response.status_code == 401
    data = response.json()
    assert data["error_code"] == "UNAUTHORIZED"
    assert "details" in data


def test_protected_route_with_passcode_returns_200(client, auth_headers):
    response = client.get("/api/test-protected", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_spa_fallback_serves_index_for_non_api_paths(client):
    from pathlib import Path
    web_dist = Path(__file__).parent.parent.parent / "web" / "dist"
    index_file = web_dist / "index.html"
    created_dummy = False
    if not index_file.exists():
        web_dist.mkdir(parents=True, exist_ok=True)
        index_file.write_text("<!doctype html><html><body>Vaari</body></html>", encoding="utf-8")
        created_dummy = True

    try:
        # Desk route
        response = client.get("/desk")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert "<!doctype html>" in response.text.lower()

        # Arbitrary non-api client route
        response2 = client.get("/driver/some-token-path")
        assert response2.status_code == 200
        assert "text/html" in response2.headers.get("content-type", "")
        assert "<!doctype html>" in response2.text.lower()
    finally:
        if created_dummy:
            try:
                index_file.unlink()
            except Exception:
                pass

