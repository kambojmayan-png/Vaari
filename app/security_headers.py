"""Standard security headers on every response (pilot v0.2).

Driver and record links carry their token in the URL, so the Referrer-Policy
is ``no-referrer``: following any outbound link (wa.me, map tiles) never
sends the token to another site. API responses are never cached.
"""

from starlette.middleware.cors import CORSMiddleware

from app.config import settings

# The SPA is built by Vite: one module script and one stylesheet from /assets,
# React inline style attributes, images from the API as blob: URLs, and the
# optional Desk map's OpenStreetMap tiles.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https://tile.openstreetmap.org",
        "connect-src 'self'",
        "font-src 'self' data:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

BASE_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(self), geolocation=(self), microphone=(), payment=(), usb=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
]

HSTS = (b"strict-transport-security", b"max-age=31536000; includeSubDomains")


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope.get("path", "").startswith("/api")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for k, v in BASE_HEADERS:
                    if k not in present:
                        headers.append((k, v))
                if settings.is_production and HSTS[0] not in present:
                    headers.append(HSTS)
                if is_api and b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class ConfiguredCORSMiddleware:
    """CORS for exactly the origins in VAARI_CORS_ORIGINS, read on each request.

    With no origins configured it adds nothing, so browsers keep the default
    same-origin rule and other sites cannot read API responses.
    """

    def __init__(self, app):
        self.app = app
        self._cached: tuple[tuple[str, ...], CORSMiddleware] | None = None

    def _cors_for(self, origins: tuple[str, ...]) -> CORSMiddleware:
        if self._cached is None or self._cached[0] != origins:
            self._cached = (
                origins,
                CORSMiddleware(
                    self.app,
                    allow_origins=list(origins),
                    allow_credentials=False,
                    allow_methods=["GET", "POST", "PATCH", "DELETE"],
                    allow_headers=[
                        "Authorization",
                        "Content-Type",
                        "X-Vaari-Passcode",
                        "X-Vaari-Slot-Token",
                        "X-Vaari-Machine-Token",
                        "X-Request-ID",
                    ],
                    expose_headers=["Retry-After", "X-Request-ID"],
                    max_age=600,
                ),
            )
        return self._cached[1]

    async def __call__(self, scope, receive, send):
        origins = tuple(settings.cors_origins)
        if scope["type"] != "http" or not origins:
            await self.app(scope, receive, send)
            return
        await self._cors_for(origins)(scope, receive, send)
