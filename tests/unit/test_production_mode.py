"""Production mode refuses to start with unsafe settings (pilot items A1, A2)."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.startup_checks import UnsafeConfigError, config_problems, enforce_startup_checks

STRONG = "a-strong-session-secret-for-tests-2026-xyz"


@pytest.fixture
def prod(monkeypatch):
    monkeypatch.setenv("VAARI_ENV", "production")
    monkeypatch.setenv("VAARI_SECRET_KEY", STRONG)
    monkeypatch.setenv("VAARI_READER", "mock")
    monkeypatch.setenv("VAARI_ALLOW_HOSTED_READER", "false")
    monkeypatch.delenv("VAARI_ALLOW_HOSTED_READER_IN_PRODUCTION", raising=False)
    return monkeypatch


def test_development_mode_accepts_default_passcode(monkeypatch):
    monkeypatch.setenv("VAARI_ENV", "development")
    monkeypatch.setenv("VAARI_DEMO_PASSCODE", "change-me")
    assert config_problems(settings) == []


def test_unknown_env_value_is_refused(monkeypatch):
    monkeypatch.setenv("VAARI_ENV", "staging")
    problems = config_problems(settings)
    assert len(problems) == 1 and "VAARI_ENV" in problems[0]


def test_production_with_safe_settings_has_no_problems(prod):
    assert config_problems(settings) == []


@pytest.mark.parametrize(
    "secret, needle",
    [("", "empty"), ("   ", "empty"), ("change-me", "default"), ("x" * 31, "31 characters")],
)
def test_production_refuses_weak_secret(prod, secret, needle):
    prod.setenv("VAARI_SECRET_KEY", secret)
    problems = config_problems(settings)
    assert any(needle in p for p in problems), problems


def test_production_accepts_secret_of_exactly_32(prod):
    prod.setenv("VAARI_SECRET_KEY", "x" * 32)
    assert config_problems(settings) == []


def test_production_ignores_the_shared_passcode(prod):
    # The passcode is switched off in production, so its value cannot make startup unsafe.
    prod.setenv("VAARI_DEMO_PASSCODE", "change-me")
    assert config_problems(settings) == []


@pytest.mark.parametrize(
    "reader, allow", [("hosted", "false"), ("mock", "true"), ("hosted", "true")]
)
def test_production_refuses_hosted_reader_without_override(prod, reader, allow):
    prod.setenv("VAARI_READER", reader)
    prod.setenv("VAARI_ALLOW_HOSTED_READER", allow)
    problems = config_problems(settings)
    assert any("third party" in p for p in problems), problems


def test_production_hosted_reader_with_explicit_override(prod):
    prod.setenv("VAARI_READER", "hosted")
    prod.setenv("VAARI_ALLOW_HOSTED_READER", "true")
    prod.setenv("VAARI_ALLOW_HOSTED_READER_IN_PRODUCTION", "true")
    # Part 5: the hosted reader also needs a model name and a key before it may start.
    prod.setenv("VAARI_VISION_MODEL", "a-current-gemini-model")
    prod.setenv("GEMINI_API_KEY", "synthetic-test-key")
    assert config_problems(settings) == []


def test_all_problems_listed_together(prod):
    prod.setenv("VAARI_SECRET_KEY", "change-me")
    prod.setenv("VAARI_READER", "hosted")
    with pytest.raises(UnsafeConfigError) as exc:
        enforce_startup_checks(settings)
    assert len(exc.value.problems) == 2
    assert "refused to start" in str(exc.value)


def test_app_refuses_to_start_in_production_with_default_secret(prod, temp_db):
    prod.setenv("VAARI_SECRET_KEY", "change-me")
    with pytest.raises(UnsafeConfigError):
        with TestClient(app):
            pass


def test_app_starts_in_production_with_safe_settings(prod, temp_db):
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
