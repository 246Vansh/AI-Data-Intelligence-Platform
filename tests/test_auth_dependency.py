"""
Auth Step 3 - get_current_user() backed by the session cookie.

These tests switch the conftest development bypass OFF, so requests
must carry a valid session cookie. Users and sessions live in the
per-test temporary auth database set up by tests/conftest.py. Password
hashing is stubbed in backend.auth.store (cookies, not passwords, are
under test here).
"""

import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

import backend.auth.config as config_module
import backend.auth.store as store_module
import backend.dependencies as dependencies_module
import backend.main as main_module
import backend.routes.analysis as analysis_route
import backend.routes.dataset as dataset_route
from backend.auth.config import (
    AUTH_COOKIE_NAME_ENV_VAR,
    AUTH_COOKIE_SAMESITE_ENV_VAR,
    AUTH_COOKIE_SECURE_ENV_VAR,
    AUTH_DEV_MODE_ENV_VAR,
    DEFAULT_COOKIE_NAME,
    load_auth_settings,
)
from backend.auth.sessions import SessionService
from backend.auth.store import AUTH_DB_PATH_ENV_VAR, CredentialStore
from backend.dependencies import DEV_USER_ID_ENV_VAR, get_current_user
from backend.main import app
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetRegistry


CSV = b"region,revenue\nNorth,10\nSouth,20\n"
UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"

# Every route that depends on get_current_user.
PROTECTED_ROUTES = [
    ("post", "/api/dataset/upload"),
    ("get", "/api/dataset"),
    ("get", f"/api/dataset/{UNKNOWN_ID}"),
    ("delete", f"/api/dataset/{UNKNOWN_ID}"),
    ("get", "/api/dataset/profile"),
    ("get", f"/api/dataset/{UNKNOWN_ID}/profile"),
    ("get", "/api/dataset/preview"),
    ("get", f"/api/dataset/{UNKNOWN_ID}/preview"),
    ("get", "/api/dataset/quality"),
    ("get", f"/api/dataset/{UNKNOWN_ID}/quality"),
    ("get", "/api/dataset/metadata"),
    ("get", f"/api/dataset/{UNKNOWN_ID}/metadata"),
    ("post", "/api/analyze"),
    ("post", "/api/jobs/analysis"),
    ("get", f"/api/jobs/{UNKNOWN_ID}"),
]

NOT_AUTHENTICATED = {"detail": "Not authenticated."}


@pytest.fixture(autouse=True)
def real_auth(monkeypatch):
    """Turn the conftest development bypass off for this module."""
    monkeypatch.delenv(AUTH_DEV_MODE_ENV_VAR, raising=False)
    monkeypatch.setattr(store_module, "hash_password", lambda password: "stub-hash")


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    monkeypatch.setattr(dataset_route, "dataset_registry", registry)
    monkeypatch.setattr(dataset_route, "dataset_manager", manager)
    monkeypatch.setattr(dataset_route, "PARQUET_STORAGE_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setattr(dependencies_module, "dataset_manager", manager)
    monkeypatch.setattr(analysis_route, "dataset_registry", registry)

    return registry


@pytest.fixture
def auth_db():
    return load_auth_settings().db_path


@pytest.fixture
def users(auth_db):
    store = CredentialStore(auth_db)
    return (
        store.create_user("alice@example.com", "alice password 123"),
        store.create_user("bob@example.com", "bob password 12345"),
    )


@pytest.fixture
def sessions(auth_db):
    return SessionService(auth_db)


def _client(token=None, cookie_name=DEFAULT_COOKIE_NAME):
    client = TestClient(app)
    if token is not None:
        client.cookies.set(cookie_name, token)
    return client


def _upload(client):
    return client.post(
        "/api/dataset/upload", files={"file": ("sales.csv", CSV, "text/csv")}
    )


# =========================================================
# AUTHENTICATION REQUIRED
# =========================================================


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_protected_routes_reject_missing_cookie(isolated, method, path):
    response = getattr(_client(), method)(path)

    assert response.status_code == 401
    assert response.json() == NOT_AUTHENTICATED


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_protected_routes_reject_invalid_cookie(isolated, users, method, path):
    response = getattr(_client("forged-token-value"), method)(path)

    assert response.status_code == 401
    assert response.json() == NOT_AUTHENTICATED


def test_root_status_route_stays_public():
    assert _client().get("/").status_code == 200


def test_expired_cookie_rejected(isolated, users, sessions, auth_db):
    alice, _ = users
    token = sessions.create_session(alice.id).token

    with sqlite3.connect(auth_db) as connection:
        connection.execute(
            "UPDATE sessions SET expires_at = '2000-01-01T00:00:00.000000+00:00'"
        )

    response = _client(token).get("/api/dataset")

    assert response.status_code == 401
    assert response.json() == NOT_AUTHENTICATED


def test_idle_expired_cookie_rejected(isolated, users, sessions, auth_db):
    alice, _ = users
    token = sessions.create_session(alice.id).token

    with sqlite3.connect(auth_db) as connection:
        connection.execute(
            "UPDATE sessions SET last_seen_at = '2000-01-01T00:00:00.000000+00:00'"
        )

    assert _client(token).get("/api/dataset").status_code == 401


def test_revoked_cookie_rejected(isolated, users, sessions):
    alice, _ = users
    token = sessions.create_session(alice.id).token
    client = _client(token)
    assert client.get("/api/dataset").status_code == 200

    sessions.revoke_session(token)

    assert client.get("/api/dataset").status_code == 401


def test_session_of_deleted_user_rejected(isolated, users, sessions, auth_db):
    alice, _ = users
    token = sessions.create_session(alice.id).token

    with sqlite3.connect(auth_db) as connection:
        connection.execute("DELETE FROM users WHERE id = ?", (alice.id,))

    assert _client(token).get("/api/dataset").status_code == 401


def test_cookie_under_a_different_name_is_ignored(isolated, users, sessions):
    alice, _ = users
    token = sessions.create_session(alice.id).token

    response = _client(token, cookie_name="session").get("/api/dataset")

    assert response.status_code == 401


def test_configured_cookie_name_is_used(isolated, users, sessions, monkeypatch):
    monkeypatch.setenv(AUTH_COOKIE_NAME_ENV_VAR, "custom_sid")
    alice, _ = users
    token = sessions.create_session(alice.id).token

    assert _client(token, cookie_name="custom_sid").get("/api/dataset").status_code == 200
    assert _client(token).get("/api/dataset").status_code == 401


# =========================================================
# IDENTITY RESOLUTION
# =========================================================


def test_valid_cookie_resolves_user_uuid(isolated, users, sessions):
    alice, _ = users
    token = sessions.create_session(alice.id).token

    response = _upload(_client(token))

    assert response.status_code == 200, response.text
    dataset_id = response.json()["dataset_id"]
    assert isolated.get(dataset_id).owner_id == alice.id


def test_identity_is_never_taken_from_headers_query_or_env(isolated, users, monkeypatch):
    alice, _ = users
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, alice.id)
    client = _client()

    assert client.get("/api/dataset", headers={"X-User-Id": alice.id}).status_code == 401
    assert client.get(f"/api/dataset?user_id={alice.id}").status_code == 401
    assert client.get("/api/dataset", headers={"Authorization": f"Bearer {alice.id}"}).status_code == 401


def test_raw_user_id_as_cookie_is_rejected(isolated, users):
    alice, _ = users

    assert _client(alice.id).get("/api/dataset").status_code == 401


def test_direct_call_without_request_is_unauthenticated():
    with pytest.raises(Exception) as excinfo:
        get_current_user()

    assert getattr(excinfo.value, "status_code", None) == 401


# =========================================================
# OWNERSHIP WITH REAL SESSIONS
# =========================================================


@pytest.mark.parametrize("suffix", ["", "/profile", "/preview", "/quality", "/metadata"])
def test_one_users_cookie_cannot_access_anothers_dataset(isolated, users, sessions, suffix):
    alice, bob = users
    alice_client = _client(sessions.create_session(alice.id).token)
    bob_client = _client(sessions.create_session(bob.id).token)

    dataset_id = _upload(alice_client).json()["dataset_id"]

    assert alice_client.get(f"/api/dataset/{dataset_id}{suffix}").status_code == 200

    response = bob_client.get(f"/api/dataset/{dataset_id}{suffix}")
    assert response.status_code == 404
    assert response.json() == {"detail": f"No dataset found for dataset_id: {dataset_id!r}"}


def test_other_user_cannot_delete_or_list_dataset(isolated, users, sessions):
    alice, bob = users
    alice_client = _client(sessions.create_session(alice.id).token)
    bob_client = _client(sessions.create_session(bob.id).token)
    dataset_id = _upload(alice_client).json()["dataset_id"]

    assert bob_client.delete(f"/api/dataset/{dataset_id}").status_code == 404
    assert bob_client.get("/api/dataset").json() == {"datasets": []}

    listed = alice_client.get("/api/dataset").json()["datasets"]
    assert [d["dataset_id"] for d in listed] == [dataset_id]


# =========================================================
# DEV MODE GUARD
# =========================================================


def test_dev_mode_is_off_by_default(monkeypatch):
    monkeypatch.delenv(AUTH_DEV_MODE_ENV_VAR, raising=False)

    assert load_auth_settings().dev_mode is False


def test_dev_mode_explicitly_enabled_uses_dev_identity(isolated, monkeypatch, caplog):
    monkeypatch.setenv(AUTH_DEV_MODE_ENV_VAR, "1")
    monkeypatch.setenv(AUTH_COOKIE_SECURE_ENV_VAR, "0")
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "local-dev")
    monkeypatch.setattr(dependencies_module, "_dev_mode_warned", type(dependencies_module._dev_mode_warned)())

    with caplog.at_level(logging.WARNING, logger="backend.dependencies"):
        assert get_current_user().user_id == "local-dev"
        assert get_current_user().user_id == "local-dev"

    warnings = [r for r in caplog.records if "AUTH_DEV_MODE is active" in r.getMessage()]
    assert len(warnings) == 1


def test_dev_mode_refused_when_secure_cookies_enabled(isolated, monkeypatch, caplog):
    monkeypatch.setenv(AUTH_DEV_MODE_ENV_VAR, "1")
    monkeypatch.delenv(AUTH_COOKIE_SECURE_ENV_VAR, raising=False)  # default: Secure on
    monkeypatch.setattr(config_module, "_refusal_logged", type(config_module._refusal_logged)())

    with caplog.at_level(logging.ERROR, logger="backend.auth.config"):
        assert load_auth_settings().dev_mode is False

    assert "ignored" in caplog.text
    assert _client().get("/api/dataset").status_code == 401


@pytest.mark.parametrize("value", ["", "0", "false", "off", "maybe"])
def test_dev_mode_not_enabled_by_non_true_values(monkeypatch, value):
    monkeypatch.setenv(AUTH_DEV_MODE_ENV_VAR, value)
    monkeypatch.setenv(AUTH_COOKIE_SECURE_ENV_VAR, "0")

    assert load_auth_settings().dev_mode is False


# =========================================================
# COOKIE SETTINGS
# =========================================================


def test_cookie_settings_defaults(monkeypatch):
    for name in (AUTH_COOKIE_NAME_ENV_VAR, AUTH_COOKIE_SECURE_ENV_VAR, AUTH_COOKIE_SAMESITE_ENV_VAR):
        monkeypatch.delenv(name, raising=False)

    settings = load_auth_settings()

    assert settings.cookie_name == "aidi_session"
    assert settings.cookie_httponly is True
    assert settings.cookie_secure is True
    assert settings.cookie_samesite == "strict"
    assert settings.cookie_kwargs() == {
        "key": "aidi_session",
        "httponly": True,
        "secure": True,
        "samesite": "strict",
        "path": "/",
        "max_age": 7 * 24 * 3600,
    }


def test_secure_flag_can_be_disabled_for_local_http(monkeypatch):
    monkeypatch.setenv(AUTH_COOKIE_SECURE_ENV_VAR, "false")

    assert load_auth_settings().cookie_secure is False


@pytest.mark.parametrize("value,expected", [("lax", "lax"), ("STRICT", "strict"), ("none", "strict"), ("bogus", "strict")])
def test_samesite_allows_only_strict_or_lax(monkeypatch, value, expected):
    monkeypatch.setenv(AUTH_COOKIE_SAMESITE_ENV_VAR, value)

    assert load_auth_settings().cookie_samesite == expected


# =========================================================
# FAILURE HANDLING AND LOGGING
# =========================================================


def test_unavailable_auth_store_returns_503(isolated, monkeypatch, tmp_path):
    # A directory where the database file should be: SQLite cannot open it.
    unopenable = tmp_path / "is_a_directory"
    unopenable.mkdir()
    monkeypatch.setenv(AUTH_DB_PATH_ENV_VAR, str(unopenable))

    response = _client("some-token").get("/api/dataset")

    assert response.status_code == 503
    assert "is_a_directory" not in response.text


def test_tokens_never_logged(isolated, users, sessions, caplog):
    alice, _ = users
    token = sessions.create_session(alice.id).token

    with caplog.at_level(logging.DEBUG):
        _client(token).get("/api/dataset")
        _client(token + "x").get("/api/dataset")

    assert token not in caplog.text


# =========================================================
# STARTUP CLEANUP
# =========================================================


def test_startup_cleanup_removes_only_expired_sessions(users, sessions, auth_db):
    alice, bob = users
    live = sessions.create_session(alice.id).token
    sessions.create_session(bob.id)

    with sqlite3.connect(auth_db) as connection:
        connection.execute(
            "UPDATE sessions SET expires_at = '2000-01-01T00:00:00.000000+00:00' "
            "WHERE user_id = ?",
            (bob.id,),
        )

    main_module._cleanup_expired_sessions()

    with sqlite3.connect(auth_db) as connection:
        assert [r[0] for r in connection.execute("SELECT user_id FROM sessions")] == [alice.id]
    assert sessions.validate_session(live) is not None


def test_startup_cleanup_does_not_create_auth_db(auth_db):
    import os

    assert not os.path.exists(auth_db)

    main_module._cleanup_expired_sessions()

    assert not os.path.exists(auth_db)


def test_startup_cleanup_failure_never_raises(users, monkeypatch, caplog):
    def boom(settings):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(main_module, "get_session_service", boom)

    with caplog.at_level(logging.WARNING, logger="backend.main"):
        main_module._cleanup_expired_sessions()

    assert "Startup session cleanup skipped" in caplog.text
