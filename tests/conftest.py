"""
Shared test configuration.

Auth Step 3: the API now requires a session cookie. Most existing route
tests predate real authentication and identify callers through the
development identity (DEV_USER_ID, switched per test with
monkeypatch.setenv). To keep them unchanged, every test runs with the
explicit development bypass enabled - which, by design, is honoured
only with Secure cookies off - and with the auth database redirected
to a per-test temporary file so nothing ever touches data/auth.db.

Tests that exercise real cookie authentication opt out by deleting
AUTH_DEV_MODE (see tests/test_auth_dependency.py).
"""

import pytest

from backend.auth.config import AUTH_COOKIE_SECURE_ENV_VAR, AUTH_DEV_MODE_ENV_VAR
from backend.auth.store import AUTH_DB_PATH_ENV_VAR


@pytest.fixture(autouse=True)
def _auth_test_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(AUTH_DEV_MODE_ENV_VAR, "1")
    monkeypatch.setenv(AUTH_COOKIE_SECURE_ENV_VAR, "0")
    monkeypatch.setenv(AUTH_DB_PATH_ENV_VAR, str(tmp_path / "test_auth.db"))
