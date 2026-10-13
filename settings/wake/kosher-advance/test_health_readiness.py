"""Readiness probe tests: process-up vs database-writable.

Built for BRIEF W5-PROJECT-LOOP-AND-KOSHER-FILTER. The gap is recorded in
docs/IMPLEMENTATION_BACKLOG.md (2026-09-14 audit): "No readiness endpoint
(/health?deep=true is auth-gated; verified 401 live), so 'process up' and
'database writable' are indistinguishable to an orchestrator."

These tests call the endpoint function directly with a stub deps object, so they
need no database, no auth and no env; the point is that the endpoint itself
performs NO authorization and turns the storage verdict into 200/503.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routers import health


class _Storage:
    def __init__(self, writable: bool, error: Exception | None = None):
        self._writable = writable
        self._error = error

    def health_check(self):
        if self._error is not None:
            raise self._error
        return {"writable": self._writable, "quick_check": "ok"}


class _Deps:
    def __init__(self, storage):
        self.storage = storage


def test_readyz_route_exists():
    paths = {getattr(r, "path", None) for r in health.router.routes}
    assert "/readyz" in paths


def test_readyz_is_ok_when_db_is_writable():
    body = health.readiness(_Deps(_Storage(True)))
    assert body["status"] == "ok"
    assert body["db"]["writable"] is True


def test_readyz_is_503_when_db_is_not_writable():
    with pytest.raises(HTTPException) as ei:
        health.readiness(_Deps(_Storage(False)))
    assert ei.value.status_code == 503
    assert ei.value.detail["status"] == "error"


def test_readyz_is_503_and_names_the_error_when_health_check_raises():
    with pytest.raises(HTTPException) as ei:
        health.readiness(_Deps(_Storage(True, RuntimeError("db down"))))
    assert ei.value.status_code == 503
    assert ei.value.detail["db"]["error"] == "RuntimeError"
