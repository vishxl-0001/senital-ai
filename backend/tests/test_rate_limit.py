"""
Phase 5 verification — item 17: slowapi actually enforces a 429.

The suite disables rate limiting globally (conftest) so endpoints can be called
directly. This test builds its OWN FastAPI app with an ENABLED limiter and a tiny
limit, then confirms requests past the limit get HTTP 429 — proving the wiring
(limiter + exception handler + per-caller key) works.
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.rate_limit import _caller_key


def _make_app():
    limiter = Limiter(key_func=_caller_key, enabled=True)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.get("/ping")
    @limiter.limit("3/minute")
    async def ping(request: Request):
        return {"ok": True}

    return app


def test_returns_429_after_limit():
    client = TestClient(_make_app())
    codes = [client.get("/ping").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200], codes
    assert codes[3] == 429 and codes[4] == 429, codes


def test_per_caller_key_isolates_api_keys():
    """Different X-API-Key callers get independent buckets."""
    client = TestClient(_make_app())
    # Caller A exhausts its bucket.
    for _ in range(3):
        assert client.get("/ping", headers={"X-API-Key": "aaaaaaaaaaaa1"}).status_code == 200
    assert client.get("/ping", headers={"X-API-Key": "aaaaaaaaaaaa1"}).status_code == 429
    # Caller B is unaffected.
    assert client.get("/ping", headers={"X-API-Key": "bbbbbbbbbbbb2"}).status_code == 200
