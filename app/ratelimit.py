"""Rate limiting and sign-in lockout (pilot v0.2).

In-memory and per process: right for one server at one centre. With more
than one server process, each keeps its own counts (see docs/DEPLOY.md).

- ``RateLimitMiddleware`` caps sign-in attempts and photo uploads per client
  address, *before* the request body is read, so a flood of large uploads is
  turned away cheaply.
- ``LoginLockout`` locks a username after repeated wrong passwords. It works
  the same for usernames that do not exist, so the answer does not reveal
  which accounts exist.
"""

import json
import math
import re
import threading
from collections import deque

from app import clock
from app.config import settings


class SlidingWindow:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, bucket: str, key: str, limit: int, window_s: float) -> float:
        """Record a hit. Return 0 if allowed, else seconds until the next hit is allowed."""
        now = clock.monotonic()
        with self._lock:
            q = self._hits.setdefault((bucket, key), deque())
            while q and q[0] <= now - window_s:
                q.popleft()
            if limit <= 0:
                return window_s
            if len(q) >= limit:
                return max(0.0, q[0] + window_s - now)
            q.append(now)
            return 0.0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class LoginLockout:
    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def seconds_locked(self, username: str) -> float:
        now = clock.monotonic()
        with self._lock:
            until = self._locked_until.get(username)
            if until is None:
                return 0.0
            if until <= now:
                self._locked_until.pop(username, None)
                self._failures.pop(username, None)
                return 0.0
            return until - now

    def record_failure(self, username: str) -> bool:
        """Record a wrong password. Return True if this failure locks the username."""
        now = clock.monotonic()
        window = settings.login_lockout_minutes * 60
        with self._lock:
            recent = [t for t in self._failures.get(username, []) if t > now - window]
            recent.append(now)
            self._failures[username] = recent
            if len(recent) >= settings.login_lockout_failures:
                self._locked_until[username] = now + window
                return True
            return False

    def record_success(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username, None)
            self._locked_until.pop(username, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


limiter = SlidingWindow()
lockout = LoginLockout()

_UPLOAD_PATHS = [
    re.compile(r"^/api/intake/register-photo$"),
    re.compile(r"^/api/slots/[^/]+/(start|done)$"),
]


def client_key(scope: dict) -> str:
    if settings.trust_proxy:
        for name, value in scope.get("headers") or []:
            if name == b"x-forwarded-for":
                first = value.decode("latin-1").split(",")[0].strip()
                if first:
                    return first
    client = scope.get("client")
    return client[0] if client else "unknown"


def retry_after_seconds(wait_s: float) -> int:
    return max(1, math.ceil(wait_s))


def rate_limited_body(wait_s: float, message: str) -> bytes:
    return json.dumps(
        {
            "error_code": "RATE_LIMITED",
            "message": message,
            "details": {"retry_after_s": retry_after_seconds(wait_s)},
        }
    ).encode("utf-8")


class RateLimitMiddleware:
    """Pure ASGI middleware: checks limits from the path alone, before the body is read."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        rule = None
        if path == "/api/auth/login":
            rule = ("login", settings.login_rate_per_min, "Too many sign-in attempts. Wait a minute and try again.")
        elif any(p.match(path) for p in _UPLOAD_PATHS):
            rule = ("upload", settings.upload_rate_per_min, "Too many uploads. Wait a minute and try again.")
        if rule is None:
            await self.app(scope, receive, send)
            return

        bucket, limit, message = rule
        wait_s = limiter.hit(bucket, client_key(scope), limit, 60.0)
        if wait_s <= 0:
            await self.app(scope, receive, send)
            return

        body = rate_limited_body(wait_s, message)
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(retry_after_seconds(wait_s)).encode()),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
