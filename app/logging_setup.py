"""Structured JSON logs with request IDs (pilot item C9).

Rules, enforced in code and by tests:

- One JSON object per line on stdout.
- Every line written while handling a request carries its ``request_id``. The
  ID comes from a well-formed ``X-Request-ID`` header or is generated, and is
  returned in the response's ``X-Request-ID`` header.
- Access lines name the *route template* (``/api/records/{token}``), never the
  real path or query string, so tokens, villages and dates never reach a log.
- Never logged: names, phone numbers, images, request or response bodies,
  reader output. A redaction filter also masks anything that looks like an
  Indian mobile number or a link token, in case a message slips through.
- Unhandled errors log the exception type and the code location only, not the
  message, because database errors can quote the values they failed on.
"""

import contextvars
import json
import logging
import re
import sys
import traceback
import uuid

from app import clock

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("vaari_request_id", default=None)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
# secrets.token_urlsafe(16): 22 base64url characters. Requiring a small letter plus a capital or
# a digit keeps ordinary snake_case identifiers (enforce_startup_checks) readable.
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]{0,21}[a-z])(?=[A-Za-z0-9_-]{0,21}[A-Z0-9])"
    r"[A-Za-z0-9_-]{22}(?![A-Za-z0-9_-])"
)
_BEARER_RE = re.compile(r"(?i)bearer\s+\S+")

# Extra fields a log call may attach (logger.info("...", extra={"fields": {...}})).
ALLOWED_FIELDS = {
    "method", "route", "status", "duration_ms", "event", "env", "auth", "reader", "provider",
    "model", "latency_ms", "rows", "ok", "revision", "error_type", "where", "counts", "checks",
}


def redact(text: str) -> str:
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _PHONE_RE.sub("[phone]", text)
    return _TOKEN_RE.sub("[token]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": clock.iso_z(clock.now_utc()),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        if rid:
            out["request_id"] = rid
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for k, v in fields.items():
                if k in ALLOWED_FIELDS:
                    out[k] = redact(v) if isinstance(v, str) else v
        return json.dumps(out, ensure_ascii=False, default=str)


_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Send every log line (ours and uvicorn's) through the JSON formatter on stdout."""
    global _configured
    root = logging.getLogger()
    if _configured:
        return
    already_json = any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)
    if not already_json:  # uvicorn --log-config app/uvicorn_logging.json sets it up already
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler.set_name("vaari-json")
        root.handlers = [h for h in root.handlers if h.get_name() != "vaari-json"] + [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # uvicorn's access log prints the raw path, which can hold a driver or record token.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # httpx logs full URLs at INFO; a hosted reader's URL can carry its API key.
    for noisy in ("httpx", "httpcore", "multipart", "PIL", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


log = logging.getLogger("vaari")


def log_event(msg: str, **fields) -> None:
    log.info(msg, extra={"fields": fields})


def _route_template(scope: dict) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None)
    path = scope.get("path", "")
    if not template:
        return "/api/(unmatched)" if path.startswith("/api") else "(static)"
    if path.startswith("/api") and not template.startswith("/api"):
        template = "/api" + template
    if template == "/{full_path:path}":
        return "(spa)"
    return template


def error_location(exc: BaseException) -> str:
    tb = traceback.extract_tb(exc.__traceback__)
    app_frames = [f for f in tb if "/app/" in f.filename.replace("\\", "/")]
    f = (app_frames or tb or [None])[-1]
    if f is None:
        return "unknown"
    fname = f.filename.replace("\\", "/").split("/app/")[-1]
    return f"app/{fname}:{f.lineno}:{f.name}"


class RequestContextMiddleware:
    """Give every request an ID, return it, and write one access line per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = None
        for name, value in scope.get("headers") or []:
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        rid = incoming if incoming and _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        started = clock.monotonic()
        status_holder = {"status": 500}

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", rid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        response_started = {"v": False}

        async def tracking_send(message):
            if message["type"] == "http.response.start":
                response_started["v"] = True
            await send_with_id(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            # Type and code location only: the message could quote personal data.
            log.error(
                "unhandled error",
                extra={"fields": {"event": "unhandled_error", "error_type": type(exc).__name__, "where": error_location(exc)}},
            )
            status_holder["status"] = 500
            if response_started["v"]:
                raise
            body = json.dumps(
                {
                    "error_code": "INTERNAL_ERROR",
                    "message": "Something went wrong on the server. It has been logged.",
                    "details": {"request_id": rid},
                }
            ).encode()
            await send_with_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send_with_id({"type": "http.response.body", "body": body})
        finally:
            log.info(
                "request",
                extra={
                    "fields": {
                        "event": "request",
                        "method": scope.get("method"),
                        "route": _route_template(scope),
                        "status": status_holder["status"],
                        "duration_ms": round((clock.monotonic() - started) * 1000, 1),
                    }
                },
            )
            request_id_var.reset(token)
