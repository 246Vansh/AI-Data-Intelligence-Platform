"""
Auth Step 2 - SQLite-backed session service.

Every test uses a temporary SQLite file with temporary users;
AUTH_DB_PATH is redirected for the whole module so nothing can touch
data/auth.db. Time is driven by an injected fake clock, never sleep().
Password hashing is stubbed inside backend.auth.store only (sessions do
not depend on it), so creating test users doesn't pay scrypt's cost.
"""

import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import backend.auth.store as store_module
from backend.auth.sessions import (
    DEFAULT_ABSOLUTE_LIFETIME,
    DEFAULT_IDLE_TIMEOUT,
    SESSION_ABSOLUTE_LIFETIME_ENV_VAR,
    SESSION_IDLE_TIMEOUT_ENV_VAR,
    SessionService,
    SessionStoreError,
    UnknownUserError,
    hash_token,
)
from backend.auth.store import AUTH_DB_PATH_ENV_VAR, CredentialStore


START = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, now: datetime = START):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now = self.now + timedelta(**kwargs)


@pytest.fixture(autouse=True)
def _isolated_auth_db(tmp_path, monkeypatch):
    monkeypatch.setenv(AUTH_DB_PATH_ENV_VAR, str(tmp_path / "default_auth.db"))
    monkeypatch.delenv(SESSION_IDLE_TIMEOUT_ENV_VAR, raising=False)
    monkeypatch.delenv(SESSION_ABSOLUTE_LIFETIME_ENV_VAR, raising=False)


@pytest.fixture(autouse=True)
def _fast_password_hashing(monkeypatch):
    monkeypatch.setattr(store_module, "hash_password", lambda password: "stub-hash")


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "auth.db")


@pytest.fixture
def users(db_path):
    store = CredentialStore(db_path)
    alice = store.create_user("alice@example.com", "alice password 123")
    bob = store.create_user("bob@example.com", "bob password 12345")
    return alice, bob


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def service(db_path, users, clock):
    return SessionService(db_path, clock=clock)


def _session_rows(db_path):
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            "SELECT token_hash, user_id, created_at, last_seen_at, expires_at FROM sessions"
        ).fetchall()


# =========================================================
# CREATE + VALIDATE
# =========================================================


def test_create_and_validate_session(service, users):
    alice, _ = users

    new = service.create_session(alice.id)
    info = service.validate_session(new.token)

    assert info is not None
    assert info.user_id == alice.id
    assert info.created_at == START
    assert info.expires_at == START + timedelta(days=7)
    assert len(new.token) == 43  # token_urlsafe(32)
    assert new.session.user_id == alice.id


def test_tokens_are_unique_per_session(service, users):
    alice, _ = users

    tokens = {service.create_session(alice.id).token for _ in range(20)}

    assert len(tokens) == 20


def test_only_token_hashes_are_stored(service, users, db_path):
    alice, _ = users
    new = service.create_session(alice.id)

    rows = _session_rows(db_path)
    assert len(rows) == 1
    token_hash = rows[0][0]

    assert token_hash == hashlib.sha256(new.token.encode("utf-8")).hexdigest()
    assert len(token_hash) == 64
    assert new.token not in token_hash

    for name in os.listdir(os.path.dirname(db_path)):
        with open(os.path.join(os.path.dirname(db_path), name), "rb") as fh:
            assert new.token.encode("utf-8") not in fh.read()


def test_new_session_repr_omits_raw_token(service, users):
    alice, _ = users
    new = service.create_session(alice.id)

    assert new.token not in repr(new)


def test_unknown_token_rejected(service):
    assert service.validate_session("not-a-real-token") is None


@pytest.mark.parametrize("bad", [None, "", 123, b"bytes", "x" * 10_000])
def test_malformed_token_rejected(service, bad):
    assert service.validate_session(bad) is None


def test_create_session_for_unknown_user_rejected(service, db_path):
    with pytest.raises(UnknownUserError):
        service.create_session("00000000-0000-0000-0000-000000000000")

    with pytest.raises(UnknownUserError):
        service.create_session("")

    assert _session_rows(db_path) == []


# =========================================================
# REVOCATION
# =========================================================


def test_revoked_token_rejected(service, users):
    alice, _ = users
    new = service.create_session(alice.id)

    assert service.revoke_session(new.token) is True
    assert service.validate_session(new.token) is None
    assert service.revoke_session(new.token) is False


def test_revoke_one_session_leaves_others(service, users):
    alice, _ = users
    first = service.create_session(alice.id)
    second = service.create_session(alice.id)

    service.revoke_session(first.token)

    assert service.validate_session(first.token) is None
    assert service.validate_session(second.token) is not None


def test_revoke_all_sessions_for_one_user_only(service, users):
    alice, bob = users
    alice_tokens = [service.create_session(alice.id).token for _ in range(3)]
    bob_token = service.create_session(bob.id).token

    assert service.revoke_all_sessions(alice.id) == 3

    assert all(service.validate_session(t) is None for t in alice_tokens)
    assert service.validate_session(bob_token).user_id == bob.id
    assert service.revoke_all_sessions(alice.id) == 0


# =========================================================
# EXPIRATION
# =========================================================


def test_idle_session_expires_and_is_deleted(service, users, clock, db_path):
    alice, _ = users
    new = service.create_session(alice.id)

    clock.advance(hours=2)

    assert service.validate_session(new.token) is None
    assert _session_rows(db_path) == []


def test_session_just_inside_idle_timeout_is_valid(service, users, clock):
    alice, _ = users
    new = service.create_session(alice.id)

    clock.advance(hours=2, microseconds=-1)

    assert service.validate_session(new.token) is not None


def test_activity_refreshes_idle_timeout(service, users, clock):
    alice, _ = users
    new = service.create_session(alice.id)

    clock.advance(hours=1, minutes=30)
    assert service.validate_session(new.token) is not None

    # 3.5h since creation, but only 2h-1min since last activity.
    clock.advance(hours=1, minutes=59)
    assert service.validate_session(new.token) is not None


def test_absolute_lifetime_expires_active_session(service, users, clock, db_path):
    alice, _ = users
    new = service.create_session(alice.id)

    # Stay active every hour - idle never triggers - right up to 7 days.
    for _ in range(7 * 24 - 1):
        clock.advance(hours=1)
        assert service.validate_session(new.token) is not None

    clock.advance(hours=1)

    assert service.validate_session(new.token) is None
    assert _session_rows(db_path) == []


def test_validation_does_not_extend_absolute_expiry(service, users, clock, db_path):
    alice, _ = users
    new = service.create_session(alice.id)
    original_expiry = new.session.expires_at

    clock.advance(hours=1)
    info = service.validate_session(new.token)

    assert info.expires_at == original_expiry
    assert info.last_seen_at == START + timedelta(hours=1)

    (row,) = _session_rows(db_path)
    _, _, created_raw, last_seen_raw, expires_raw = row
    assert datetime.fromisoformat(expires_raw) == original_expiry
    assert datetime.fromisoformat(created_raw) == START
    assert datetime.fromisoformat(last_seen_raw) == START + timedelta(hours=1)


def test_last_seen_never_moves_backwards(service, users, clock, db_path):
    alice, _ = users
    new = service.create_session(alice.id)

    clock.advance(minutes=30)
    service.validate_session(new.token)

    clock.advance(minutes=-10)  # clock skew backwards
    service.validate_session(new.token)

    (row,) = _session_rows(db_path)
    assert datetime.fromisoformat(row[3]) == START + timedelta(minutes=30)


def test_timestamps_are_fixed_width_utc(service, users, db_path, clock):
    alice, _ = users
    clock.now = datetime(2026, 11, 2, 12, 0, 0, 0, tzinfo=timezone.utc)  # microsecond=0

    service.create_session(alice.id)

    (row,) = _session_rows(db_path)
    for raw in row[2:]:
        assert raw.endswith("+00:00")
        assert len(raw) == len("2026-11-02T12:00:00.000000+00:00")


def test_non_utc_clock_is_normalized(db_path, users):
    ist = timezone(timedelta(hours=5, minutes=30))
    clock = FakeClock(START.astimezone(ist))
    service = SessionService(db_path, clock=clock)

    new = service.create_session(users[0].id)

    assert new.session.created_at == START
    assert new.session.created_at.tzinfo == timezone.utc


def test_naive_clock_rejected(db_path, users):
    service = SessionService(db_path, clock=lambda: datetime(2026, 11, 2, 12, 0))

    with pytest.raises(ValueError):
        service.create_session(users[0].id)


# =========================================================
# USER LIFETIME
# =========================================================


def test_session_cascades_when_user_deleted_with_fk_enforced(service, users, db_path):
    alice, bob = users
    alice_token = service.create_session(alice.id).token
    bob_token = service.create_session(bob.id).token

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM users WHERE id = ?", (alice.id,))

    assert [r[1] for r in _session_rows(db_path)] == [bob.id]
    assert service.validate_session(alice_token) is None
    assert service.validate_session(bob_token) is not None


def test_session_cannot_outlive_user_deleted_without_fk(service, users, db_path):
    alice, _ = users
    token = service.create_session(alice.id).token

    # A connection that never enabled foreign keys (SQLite's default)
    # leaves the session row orphaned...
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM users WHERE id = ?", (alice.id,))
    assert len(_session_rows(db_path)) == 1

    # ...but validation joins on users, rejects it and removes it.
    assert service.validate_session(token) is None
    assert _session_rows(db_path) == []


# =========================================================
# CLEANUP
# =========================================================


def test_cleanup_removes_expired_and_orphaned_sessions(service, users, clock, db_path):
    alice, bob = users

    idle = service.create_session(alice.id)          # will go idle
    absolute = service.create_session(alice.id)      # kept active to 7d
    orphan = service.create_session(bob.id)          # user deleted

    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM users WHERE id = ?", (bob.id,))

    # Keep `absolute` active hourly so only its 7-day lifetime ends it.
    for _ in range(7 * 24 - 1):
        clock.advance(hours=1)
        assert service.validate_session(absolute.token) is not None
    clock.advance(hours=1)  # now exactly START + 7 days

    live = service.create_session(alice.id)

    removed = service.cleanup_expired_sessions()

    assert removed == 3
    remaining = {r[0] for r in _session_rows(db_path)}
    assert remaining == {hash_token(live.token)}
    assert service.validate_session(live.token) is not None
    for gone in (idle, absolute, orphan):
        assert hash_token(gone.token) not in remaining


def test_cleanup_keeps_live_sessions(service, users, clock):
    alice, _ = users
    new = service.create_session(alice.id)

    clock.advance(hours=1)

    assert service.cleanup_expired_sessions() == 0
    assert service.validate_session(new.token) is not None


# =========================================================
# PERSISTENCE, SCHEMA, CONFIG
# =========================================================


def test_session_persists_across_service_instances(db_path, users, clock):
    alice, _ = users
    token = SessionService(db_path, clock=clock).create_session(alice.id).token

    reopened = SessionService(db_path, clock=clock)

    assert reopened.validate_session(token).user_id == alice.id


def test_existing_users_preserved_and_schema_idempotent(db_path, users):
    alice, bob = users

    SessionService(db_path)
    SessionService(db_path)

    store = CredentialStore(db_path)
    assert store.get_user_by_id(alice.id) == alice
    assert store.get_user_by_id(bob.id) == bob

    with sqlite3.connect(db_path) as connection:
        tables = {
            r[0]
            for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"users", "sessions"} <= tables


def test_service_on_fresh_database_creates_both_tables(tmp_path):
    path = str(tmp_path / "fresh" / "auth.db")

    SessionService(path)

    with sqlite3.connect(path) as connection:
        tables = {
            r[0]
            for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"users", "sessions"} <= tables


def test_default_timeouts(db_path):
    service = SessionService(db_path)

    assert service.idle_timeout == DEFAULT_IDLE_TIMEOUT == timedelta(hours=2)
    assert service.absolute_lifetime == DEFAULT_ABSOLUTE_LIFETIME == timedelta(days=7)


def test_timeouts_configurable_via_env(db_path, monkeypatch):
    monkeypatch.setenv(SESSION_IDLE_TIMEOUT_ENV_VAR, "600")
    monkeypatch.setenv(SESSION_ABSOLUTE_LIFETIME_ENV_VAR, "3600")

    service = SessionService(db_path)

    assert service.idle_timeout == timedelta(minutes=10)
    assert service.absolute_lifetime == timedelta(hours=1)


@pytest.mark.parametrize("value", ["", "abc", "0", "-5", "1.5"])
def test_invalid_env_timeouts_fall_back_to_defaults(db_path, monkeypatch, value):
    monkeypatch.setenv(SESSION_IDLE_TIMEOUT_ENV_VAR, value)
    monkeypatch.setenv(SESSION_ABSOLUTE_LIFETIME_ENV_VAR, value)

    service = SessionService(db_path)

    assert service.idle_timeout == DEFAULT_IDLE_TIMEOUT
    assert service.absolute_lifetime == DEFAULT_ABSOLUTE_LIFETIME


def test_explicit_timeouts_apply(db_path, users, clock):
    service = SessionService(
        db_path,
        idle_timeout=timedelta(minutes=5),
        absolute_lifetime=timedelta(minutes=30),
        clock=clock,
    )
    new = service.create_session(users[0].id)

    clock.advance(minutes=5)

    assert service.validate_session(new.token) is None


def test_default_path_comes_from_env_var(tmp_path, monkeypatch):
    configured = tmp_path / "configured.db"
    monkeypatch.setenv(AUTH_DB_PATH_ENV_VAR, str(configured))

    service = SessionService()

    assert service.db_path == str(configured)
    assert configured.exists()


# =========================================================
# DATABASE FAILURES
# =========================================================


def _broken_connect(*args, **kwargs):
    raise sqlite3.OperationalError("database is locked")


def test_validation_fails_closed_on_database_error(service, users, monkeypatch, caplog):
    alice, _ = users
    token = service.create_session(alice.id).token

    monkeypatch.setattr("backend.auth.sessions.sqlite3.connect", _broken_connect)

    with caplog.at_level(logging.WARNING, logger="backend.auth.sessions"):
        assert service.validate_session(token) is None

    assert "OperationalError" in caplog.text
    assert token not in caplog.text
    assert hash_token(token) not in caplog.text


def test_write_operations_raise_store_error_on_database_error(service, users, monkeypatch, caplog):
    alice, _ = users
    token = service.create_session(alice.id).token

    monkeypatch.setattr("backend.auth.sessions.sqlite3.connect", _broken_connect)

    with caplog.at_level(logging.WARNING, logger="backend.auth.sessions"):
        with pytest.raises(SessionStoreError):
            service.create_session(alice.id)
        with pytest.raises(SessionStoreError):
            service.revoke_session(token)
        with pytest.raises(SessionStoreError):
            service.revoke_all_sessions(alice.id)
        with pytest.raises(SessionStoreError):
            service.cleanup_expired_sessions()

    assert token not in caplog.text


def test_tests_never_touch_the_production_default_db():
    assert not os.path.exists(os.path.join("data", "auth.db"))
