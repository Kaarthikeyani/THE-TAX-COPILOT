"""HTTP-level protection: per-client rate limits, body-size cap, host allow-list. Who may call what is decided in
auth.py (signed-in session for the app, a per-account key for the phone's SMS webhook).

Environment (never source control):
  COPILOT_ALLOWED_HOSTS  extra comma-separated Host names accepted (localhost/127.0.0.1/::1 always are)
  COPILOT_CORS_ORIGINS   comma-separated origins allowed to call the API from another site (default: none)
  COPILOT_WEBHOOK_RATE   webhook requests per minute per client (default 60)
Rate limits are in-process (single worker). Behind a reverse proxy every client looks like the proxy's IP.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from collections import defaultdict, deque

from starlette.responses import JSONResponse

MAX_BODY = 512 * 1024
STATIC_EXT = (".html", ".js", ".css", ".png", ".svg", ".ico", ".jpg", ".webp", ".woff2", ".map", ".webmanifest")
LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]", "testserver"}


def allowed_hosts() -> set:
    extra = {h.strip().lower() for h in os.environ.get("COPILOT_ALLOWED_HOSTS", "").split(",") if h.strip()}
    for var in ("RENDER_EXTERNAL_HOSTNAME", "RAILWAY_PUBLIC_DOMAIN"):  # hosting platforms tell us their public name
        if os.environ.get(var):
            extra.add(os.environ[var].lower())
    return LOOPBACK | extra


def same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and secrets.compare_digest(a.encode(), b.encode())


class SlidingWindow:
    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float) -> tuple[bool, int]:
        """Record a hit; return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(window - (now - q[0])) + 1)
            q.append(now)
            return True, 0

    def count(self, key: str, window: float) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            return len(q)

    def reset(self):
        with self._lock:
            self._hits.clear()


LIMITS = SlidingWindow()
LIMIT_RULES = [  # (path prefix, limit, window seconds, bucket)
    ("/auth/otp", 12, 60.0, "otp"),
    ("/ask", 10, 60.0, "ask"),
    ("/stream", 30, 60.0, "stream"),
    ("/sms/webhook", int(os.environ.get("COPILOT_WEBHOOK_RATE", "60")), 60.0, "webhook"),
    ("/sms/ingest", 60, 60.0, "ingest"),
    ("/model/retrain", 6, 60.0, "retrain"),
    ("/plan", 120, 60.0, "plan"),
]
DEFAULT_LIMIT = (600, 60.0)
FAIL_LIMIT = (10, 300.0)  # failed auth attempts per client per 5 minutes


def _is_static(path: str) -> bool:
    return path == "/" or path.lower().endswith(STATIC_EXT)


def _host(h: str) -> str:
    h = h.strip().lower()
    return h.split("]")[0].lstrip("[") if h.startswith("[") else h.split(":")[0]


def _client(scope) -> str:
    c = scope.get("client")
    return c[0] if c else "unknown"


def _deny(status: int, code: str, message: str, headers=None):
    return JSONResponse({"error": code, "detail": message}, status_code=status, headers=headers or {})


class SecurityMiddleware:
    """Pure ASGI middleware so the request body is never buffered or logged here."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        method = scope["method"]
        client = _client(scope)

        host = _host(headers.get("host", ""))
        if host and host not in allowed_hosts():
            return await _deny(400, "bad_host", "Host not allowed. Set COPILOT_ALLOWED_HOSTS to add it.")(scope, receive, send)

        if method in ("POST", "PUT", "PATCH"):
            try:
                if int(headers.get("content-length", "0")) > MAX_BODY:
                    return await _deny(413, "payload_too_large", f"Body larger than {MAX_BODY // 1024} KB")(scope, receive, send)
            except ValueError:
                return await _deny(400, "bad_content_length", "Invalid Content-Length")(scope, receive, send)

        if not _is_static(path) and path != "/health":
            limit, window, bucket = DEFAULT_LIMIT[0], DEFAULT_LIMIT[1], "api"
            for prefix, lim, win, name in LIMIT_RULES:
                if path.startswith(prefix):
                    limit, window, bucket = lim, win, name
                    break
            ok, retry = LIMITS.hit(f"{bucket}:{client}", limit, window)
            if not ok:
                return await _deny(429, "rate_limited", "Too many requests. Slow down and retry.",
                                   {"Retry-After": str(retry)})(scope, receive, send)
        return await self.app(scope, receive, send)
