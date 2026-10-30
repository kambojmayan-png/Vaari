"""Startup safety checks.

In production mode (VAARI_ENV=production) the app refuses to start when a
setting is unsafe. Every problem is listed in plain words so the person
deploying can fix them all in one go.
"""

from typing import Any

from app.config import VALID_ENVS

DEFAULT_SECRETS = {"change-me", "changeme", "password", "vaari", "secret", "change-me-to-a-long-random-string"}
MIN_SECRET_LEN = 32


class UnsafeConfigError(RuntimeError):
    """Raised at startup when production settings are unsafe."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        lines = ["Vaari refused to start: unsafe settings for production mode."]
        lines += [f"  - {p}" for p in problems]
        super().__init__("\n".join(lines))


def _hosted_reader_requested(s: Any) -> bool:
    """True when a reader that sends images to a third party is switched on."""
    from app.intake.reader import reader_name

    return bool(getattr(s, "allow_hosted_reader", False)) or reader_name(s) == "gemini_demo"


def reader_problems(s: Any) -> list[str]:
    """Reader settings that cannot work, in any mode."""
    import os
    from ipaddress import ip_address
    from urllib.parse import urlparse

    from app.intake.reader import READER_NAMES, reader_name

    problems: list[str] = []
    name = reader_name(s)
    if name not in READER_NAMES:
        problems.append(f"VAARI_READER='{name}' is not a reader. Use one of: {', '.join(READER_NAMES)}.")
    if name == "gemini_demo" and getattr(s, "allow_hosted_reader", False):
        if not str(getattr(s, "vision_model", "") or "").strip():
            problems.append(
                "VAARI_VISION_MODEL is required when the hosted reader is on. Name a current Gemini vision model; "
                "there is no built-in default."
            )
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            problems.append("GEMINI_API_KEY is empty. Put it in .env (never in the code or the repo).")
    if name == "custom":
        url = str(getattr(s, "custom_reader_url", "") or "").strip()
        if not url:
            problems.append("VAARI_READER=custom needs VAARI_CUSTOM_READER_URL.")
        elif getattr(s, "is_production", False):
            parsed = urlparse(url)
            host = parsed.hostname or ""
            try:
                private = ip_address(host).is_private or ip_address(host).is_loopback
            except ValueError:
                private = host in ("localhost",)
            if parsed.scheme != "https" and not private:
                problems.append("VAARI_CUSTOM_READER_URL must use https:// unless it is on this machine or a private network.")
    return problems


def config_problems(s: Any) -> list[str]:
    """Return a list of problems with the settings. Empty means safe to start."""
    problems: list[str] = []
    env = str(getattr(s, "env", "development"))
    if env not in VALID_ENVS:
        problems.append(f"VAARI_ENV must be one of {', '.join(VALID_ENVS)} (got '{env}').")
        return problems
    store = str(getattr(s, "photo_store", "local"))
    if store != "local":
        problems.append(
            f"VAARI_PHOTO_STORE={store} is not built. Only 'local' works today (photos under VAARI_DATA_DIR)."
        )

    problems.extend(reader_problems(s))

    if env != "production":
        return problems

    # In production staff sign in with accounts; the shared passcode is switched off.
    # The secret that guards sign-in is VAARI_SECRET_KEY, which signs every session.
    secret = (getattr(s, "secret_key", "") or "").strip()
    if not secret:
        problems.append("VAARI_SECRET_KEY is empty. Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    elif secret.lower() in DEFAULT_SECRETS:
        problems.append("VAARI_SECRET_KEY is still a default value.")
    elif len(secret) < MIN_SECRET_LEN:
        problems.append(
            f"VAARI_SECRET_KEY is {len(secret)} characters; production needs at least {MIN_SECRET_LEN}."
        )

    for origin in getattr(s, "cors_origins", []) or []:
        if origin == "*" or "*" in origin:
            problems.append("VAARI_CORS_ORIGINS may not contain '*' in production. List exact origins.")
            break
        if not origin.startswith("https://"):
            problems.append(f"VAARI_CORS_ORIGINS entry '{origin}' must start with https:// in production.")

    if _hosted_reader_requested(s) and not getattr(s, "allow_hosted_reader_in_production", False):
        problems.append(
            "The hosted register reader is enabled (VAARI_READER or VAARI_ALLOW_HOSTED_READER). "
            "It sends register images to a third party and is for demonstration only. "
            "Turn it off, or set VAARI_ALLOW_HOSTED_READER_IN_PRODUCTION=true to override on purpose."
        )
    return problems


def enforce_startup_checks(s: Any) -> None:
    """Raise UnsafeConfigError if the settings are unsafe for the current mode."""
    problems = config_problems(s)
    if problems:
        raise UnsafeConfigError(problems)
