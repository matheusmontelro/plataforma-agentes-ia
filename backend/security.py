import asyncio
import hashlib
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from backend.runtime_settings import PUBLIC_APP_URL


def parse_csv_env(name: str, default: Iterable[str] = ()) -> List[str]:
    raw = os.getenv(name, "")
    values = raw.split(",") if raw else list(default)
    return [value.strip() for value in values if value.strip()]


def get_allowed_hosts() -> List[str]:
    environment = os.getenv("ENVIRONMENT", "production").lower()
    public_host = urlparse(PUBLIC_APP_URL).hostname
    defaults = (public_host,) if public_host else ()
    if environment != "production" or not defaults:
        defaults = ("localhost", "127.0.0.1", "*.localhost", "testserver")
    return parse_csv_env("ALLOWED_HOSTS", defaults)


def get_client_ip(request: Request) -> str:
    trust_proxy = os.getenv("TRUST_PROXY_HEADERS", "true").lower() == "true"
    if trust_proxy:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

    return request.client.host if request.client else "unknown"


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class InMemoryRateLimiter:
    """Small per-process limiter for auth edge protection.

    This is intentionally dependency-free. In multi-worker deployments it should
    sit behind WAF/nginx limits too, but it still blocks simple brute-force loops
    that hit a single worker.
    """

    def __init__(self) -> None:
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(
        self,
        request: Request,
        scope: str,
        identifier: Optional[str],
        *,
        limit: int,
        window_seconds: int,
    ) -> None:
        if limit <= 0 or window_seconds <= 0:
            return

        ip = get_client_ip(request)
        identity = _stable_hash(identifier.strip().lower()) if identifier else "anonymous"
        key = f"{scope}:{ip}:{identity}"
        now = time.monotonic()
        cutoff = now - window_seconds

        async with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Muitas tentativas. Tente novamente em instantes.",
                    headers={"Retry-After": str(retry_after)},
                )

            bucket.append(now)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, content_security_policy: Optional[str] = None):
        super().__init__(app)
        environment = os.getenv("ENVIRONMENT", "production").lower()
        configured_csp = content_security_policy or os.getenv("CONTENT_SECURITY_POLICY")
        if configured_csp:
            self.content_security_policy = configured_csp
        elif environment == "production":
            self.content_security_policy = (
                "default-src 'self'; "
                "base-uri 'self'; "
                "object-src 'none'; "
                "frame-ancestors 'none'; "
                "form-action 'self'; "
                "img-src 'self' data: https:; "
                "media-src 'self' data: https: blob:; "
                "font-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; "
                "connect-src 'self' https: wss:; "
                "upgrade-insecure-requests"
            )
        else:
            self.content_security_policy = None

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if self.content_security_policy:
            response.headers.setdefault("Content-Security-Policy", self.content_security_policy)

        if request.url.scheme == "https" or os.getenv("ENVIRONMENT", "production").lower() == "production":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )

        return response


auth_rate_limiter = InMemoryRateLimiter()
