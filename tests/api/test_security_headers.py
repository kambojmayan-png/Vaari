"""CORS locked to configured origins and standard security headers (pilot item A5)."""

import pytest

from app.config import settings
from app.startup_checks import config_problems


def test_security_headers_on_api_responses(client):
    r = client.get("/api/health")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert "default-src 'self'" in h["content-security-policy"]
    assert "camera=(self)" in h["permissions-policy"]
    assert h["cache-control"] == "no-store"
    assert "strict-transport-security" not in h  # development


def test_security_headers_on_errors_and_rate_limits(client, monkeypatch):
    assert client.get("/api/nope").headers["x-frame-options"] == "DENY"
    monkeypatch.setenv("VAARI_LOGIN_RATE_PER_MIN", "0")
    r = client.post("/api/auth/login", json={"username": "a", "password": "b"})
    assert r.status_code == 429
    assert r.headers["referrer-policy"] == "no-referrer"


def test_security_headers_on_spa_pages(client):
    r = client.get("/driver/some-token")
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "content-security-policy" in r.headers
    assert "cache-control" not in r.headers or r.headers["cache-control"] != "no-store"


def test_hsts_only_in_production(client, monkeypatch):
    monkeypatch.setenv("VAARI_ENV", "production")
    r = client.get("/api/health")
    assert r.headers["strict-transport-security"].startswith("max-age=31536000")


def test_no_cors_headers_by_default(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    pre = client.options(
        "/api/requests",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in pre.headers


def test_cors_allows_only_configured_origins(client, monkeypatch):
    monkeypatch.setenv("VAARI_CORS_ORIGINS", "https://desk.example.org, https://officer.example.org/")
    ok = client.get("/api/health", headers={"Origin": "https://officer.example.org"})
    assert ok.headers["access-control-allow-origin"] == "https://officer.example.org"
    bad = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers
    pre = client.options(
        "/api/requests",
        headers={
            "Origin": "https://desk.example.org",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == "https://desk.example.org"
    assert "access-control-allow-credentials" not in pre.headers
    denied = client.options(
        "/api/requests",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert denied.status_code == 400


@pytest.mark.parametrize("value", ["*", "https://*.example.org", "http://desk.example.org"])
def test_production_refuses_wildcard_or_plain_http_origins(monkeypatch, value):
    monkeypatch.setenv("VAARI_ENV", "production")
    monkeypatch.setenv("VAARI_SECRET_KEY", "s" * 40)
    monkeypatch.setenv("VAARI_READER", "mock")
    monkeypatch.setenv("VAARI_ALLOW_HOSTED_READER", "false")
    monkeypatch.setenv("VAARI_CORS_ORIGINS", value)
    assert any("VAARI_CORS_ORIGINS" in p for p in config_problems(settings))
