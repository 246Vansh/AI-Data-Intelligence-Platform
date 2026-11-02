"""
Auth Step 4 - /api/auth register, login, logout and me.

Real cookie authentication (the conftest dev bypass is switched off),
a per-test temporary auth database (tests/conftest.py), fresh
process-wide limiters per test, and scrypt at the lowest accepted cost
(ln=14) so tests stay fast - full-strength hashing is covered by
tests/test_auth_credentials.py.
"""

import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

import backend.auth.limits as limits_module
import backend.auth.passwords as passwords_module
import backend.auth.routes as routes_module
from backend.auth.config import (
    AUTH_ALLOW_REGISTRATION_ENV_VAR,
    AUTH_COOKIE_SECURE_ENV_VAR,
    AUTH_DEV_MODE_ENV_VAR,
    DEFAULT_COOKIE_NAME,
    DEV_USER_ID_ENV_VAR,
    load_auth_settings,
)
from backend.auth.limits import (
    LOGIN_MAX_FAILURES_ENV_VAR,
    LOGIN_MAX_FAILURES_PER_IP_ENV_VAR,
    LoginRateLimiter,
    PasswordCapacityError,
    PasswordWorkLimiter,
    reset_auth_limits,
)
from backend.auth.sessions import SessionService, SessionStoreError
from backend.auth.store import AUTH_DB_PATH_ENV_VAR, CredentialStore
from backend.main import app


ORIGIN = "http://localhost:5173"
HEADERS = {"Origin": ORIGIN}
EMAIL = "alice@example.com"
PASSWORD = "alice password 123"


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    monkeypatch.delenv(AUTH_DEV_MODE_ENV_VAR, raising=False)
    monkeypatch.setenv(AUTH_ALLOW_REGISTRATION_ENV_VAR, "1")
    monkeypatch.setattr(passwords_module, "SCRYPT_LOG2_N", 14)
    monkeypatch.setattr(routes_module, "_dummy_hash", None)
    reset_auth_limits()
    yield
    reset_auth_limits()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_path():
    return load_auth_settings().db_path


@pytest.fixture
def alice(db_path):
    return CredentialStore(db_path).create_user(EMAIL, PASSWORD)


def _register(client, email=EMAIL, password=PASSWORD, headers=HEADERS):
    return client.post("/api/auth/register", json={"email": email, "password": password}, headers=headers)


def _login(client, email=EMAIL, password=PASSWORD, headers=HEADERS):
    return client.post("/api/auth/login", json={"email": email, "password": password}, headers=headers)


def _set_cookie_header(response):
    return response.headers.get("set-cookie", "")


# =========================================================
# REGISTER
# =========================================================


def test_register_success_returns_safe_profile(client, db_path):
    response = _register(client, email="  New.User@Example.COM ")

    assert response.status_code == 201
    user = response.json()["user"]
    assert set(user) == {"id", "email", "created_at"}
    assert user["email"] == "new.user@example.com"
    assert "password" not in response.text and "scrypt" not in response.text

    stored = CredentialStore(db_path).get_user_by_id(user["id"])
    assert stored.password_hash.startswith("scrypt$")
    # Registration does not log the user in.
    assert "set-cookie" not in response.headers


def test_register_disabled_by_default(client, monkeypatch, db_path):
    monkeypatch.delenv(AUTH_ALLOW_REGISTRATION_ENV_VAR, raising=False)

    response = _register(client)

    assert response.status_code == 403
    assert response.json() == {"detail": "Registration is disabled."}
    assert CredentialStore(db_path).get_user_by_email(EMAIL) is None


def test_register_duplicate_email(client, alice):
    response = _register(client, email="ALICE@example.com", password="another password 1")

    assert response.status_code == 409
    assert response.json() == {"detail": "An account with this email already exists."}
    assert "scrypt" not in response.text
    assert "IntegrityError" not in response.text and "UNIQUE" not in response.text


@pytest.mark.parametrize("password", ["short", "x" * 257])
def test_register_invalid_password_is_rejected_without_echo(client, password):
    response = _register(client, password=password)

    assert response.status_code == 400
    assert "between 12 and 256" in response.json()["detail"]
    assert password not in response.text


def test_register_invalid_email(client):
    response = _register(client, email="not an email")

    assert response.status_code == 400
    assert "not an email" not in response.text


@pytest.mark.parametrize(
    "body,content_type",
    [
        (b"not json", "application/json"),
        (b"[1, 2]", "application/json"),
        (b'{"email": "a@b.com"}', "application/json"),
        (b'{"email": "a@b.com", "password": 123456789012}', "application/json"),
    ],
)
def test_malformed_bodies_rejected_with_400(client, body, content_type):
    for path in ("/api/auth/register", "/api/auth/login"):
        response = client.post(path, content=body, headers={**HEADERS, "Content-Type": content_type})
        assert response.status_code == 400, (path, response.text)


def test_oversized_body_rejected_with_413_without_echo(client):
    secret = "s" * 5000
    for path in ("/api/auth/register", "/api/auth/login"):
        response = client.post(path, json={"email": EMAIL, "password": secret}, headers=HEADERS)
        assert response.status_code == 413
        assert secret not in response.text


# =========================================================
# LOGIN
# =========================================================


def test_login_success_sets_session_cookie(client, alice, db_path):
    response = _login(client)

    assert response.status_code == 200
    assert response.json()["user"] == {
        "id": alice.id,
        "email": alice.email,
        "created_at": alice.created_at,
    }

    token = client.cookies.get(DEFAULT_COOKIE_NAME)
    assert token
    assert token not in response.text  # never in the JSON body
    assert SessionService(db_path).validate_session(token).user_id == alice.id


def test_login_cookie_flags_and_expiry(client, alice):
    header = _set_cookie_header(_login(client)).lower()

    assert header.startswith(f"{DEFAULT_COOKIE_NAME}=")
    assert "httponly" in header
    assert "samesite=strict" in header
    assert "path=/" in header
    assert f"max-age={7 * 24 * 3600}" in header
    assert "secure" not in header  # conftest: local HTTP dev setting


def test_login_cookie_secure_flag_when_enabled(client, alice, monkeypatch):
    monkeypatch.setenv(AUTH_COOKIE_SECURE_ENV_VAR, "1")

    header = _set_cookie_header(_login(client)).lower()

    assert "; secure" in header
    assert "httponly" in header


def test_wrong_password_and_unknown_email_are_indistinguishable(client, alice):
    wrong = _login(client, password="wrong password 123")
    unknown = _login(client, email="nobody@example.com")
    malformed = _login(client, email="not an email")

    for response in (wrong, unknown, malformed):
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid email or password."}
        assert "set-cookie" not in response.headers


def test_unknown_email_still_performs_scrypt_work(client, monkeypatch):
    calls = []
    real_verify = routes_module.verify_password

    def spy(password, stored):
        calls.append(stored)
        return real_verify(password, stored)

    monkeypatch.setattr(routes_module, "verify_password", spy)

    _login(client, email="nobody@example.com")

    assert len(calls) == 1 and calls[0].startswith("scrypt$")


def test_login_always_issues_fresh_token_and_retires_old(client, alice, db_path):
    _login(client)
    first = client.cookies.get(DEFAULT_COOKIE_NAME)

    _login(client)  # the client re-sends `first`
    second = client.cookies.get(DEFAULT_COOKIE_NAME)

    sessions = SessionService(db_path)
    assert second != first
    assert sessions.validate_session(first) is None
    assert sessions.validate_session(second) is not None


def test_login_never_adopts_client_supplied_token(client, alice, db_path):
    client.cookies.set(DEFAULT_COOKIE_NAME, "attacker-chosen-token")

    response = _login(client)

    # Read from the response: the client jar now holds both cookies.
    issued = response.cookies.get(DEFAULT_COOKIE_NAME)
    assert issued and issued != "attacker-chosen-token"
    assert SessionService(db_path).validate_session(issued) is not None
    assert SessionService(db_path).validate_session("attacker-chosen-token") is None


# =========================================================
# LOGOUT
# =========================================================


def test_logout_revokes_session_and_clears_cookie(client, alice, db_path):
    _login(client)
    token = client.cookies.get(DEFAULT_COOKIE_NAME)

    response = client.post("/api/auth/logout", headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {"status": "logged_out"}
    header = _set_cookie_header(response).lower()
    assert header.startswith(f"{DEFAULT_COOKIE_NAME}=")
    assert "max-age=0" in header
    assert SessionService(db_path).validate_session(token) is None

    # Even replaying the old token by hand no longer authenticates.
    replay = TestClient(app)
    replay.cookies.set(DEFAULT_COOKIE_NAME, token)
    assert replay.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("cookie", [None, "already-invalid-token"])
def test_logout_without_valid_session_still_clears_cookie(client, cookie):
    if cookie:
        client.cookies.set(DEFAULT_COOKIE_NAME, cookie)

    response = client.post("/api/auth/logout", headers=HEADERS)

    assert response.status_code == 200
    assert "max-age=0" in _set_cookie_header(response).lower()


def test_logout_storage_failure_reports_503_but_clears_cookie(client, alice, monkeypatch):
    _login(client)

    def broken(self, token):
        raise SessionStoreError("Could not revoke session.")

    monkeypatch.setattr(SessionService, "revoke_session", broken)

    response = client.post("/api/auth/logout", headers=HEADERS)

    assert response.status_code == 503
    assert "max-age=0" in _set_cookie_header(response).lower()


# =========================================================
# ME
# =========================================================


def test_me_with_session(client, alice):
    _login(client)

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": alice.id, "email": alice.email, "created_at": alice.created_at},
        "dev_mode": False,
    }


def test_me_without_session(client):
    response = client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated."}


def test_me_after_user_deleted_is_401(client, alice, db_path, monkeypatch):
    _login(client)
    # Simulate the user vanishing after session validation succeeded.
    monkeypatch.setattr(CredentialStore, "get_user_by_id", lambda self, user_id: None)

    assert client.get("/api/auth/me").status_code == 401


def test_me_in_explicit_dev_mode(client, monkeypatch):
    monkeypatch.setenv(AUTH_DEV_MODE_ENV_VAR, "1")
    monkeypatch.setenv(DEV_USER_ID_ENV_VAR, "local-dev")

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": "local-dev", "email": None, "created_at": None},
        "dev_mode": True,
    }


def test_session_cookie_from_login_authenticates_dataset_api(client, alice):
    assert client.get("/api/dataset").status_code == 401

    _login(client)

    assert client.get("/api/dataset").status_code == 200


# =========================================================
# FAILED-LOGIN RATE LIMITING
# =========================================================


def test_login_rate_limited_after_threshold(client, alice, monkeypatch):
    monkeypatch.setenv(LOGIN_MAX_FAILURES_ENV_VAR, "3")
    reset_auth_limits()

    for _ in range(3):
        assert _login(client, password="wrong password 123").status_code == 401

    blocked = _login(client, password="wrong password 123")
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0

    # Blocked even with the correct password; no cookie issued.
    correct = _login(client)
    assert correct.status_code == 429
    assert "set-cookie" not in correct.headers


def test_rate_limit_does_not_reveal_account_existence(client, alice, monkeypatch):
    monkeypatch.setenv(LOGIN_MAX_FAILURES_ENV_VAR, "2")
    reset_auth_limits()

    def run(email):
        return [_login(client, email=email, password="wrong password 123") for _ in range(3)]

    existing = run(EMAIL)
    unknown = run("nobody@example.com")

    assert [r.status_code for r in existing] == [401, 401, 429]
    assert [r.status_code for r in unknown] == [401, 401, 429]
    assert existing[-1].json() == unknown[-1].json()


def test_rate_limit_keys_on_normalized_email(client, alice, monkeypatch):
    monkeypatch.setenv(LOGIN_MAX_FAILURES_ENV_VAR, "2")
    reset_auth_limits()

    _login(client, email="ALICE@example.com", password="wrong password 123")
    _login(client, email="  alice@EXAMPLE.com ", password="wrong password 123")

    assert _login(client, email=EMAIL, password="wrong password 123").status_code == 429


def test_rate_limit_per_ip_across_emails(client, monkeypatch):
    monkeypatch.setenv(LOGIN_MAX_FAILURES_PER_IP_ENV_VAR, "4")
    reset_auth_limits()

    statuses = [
        _login(client, email=f"user{i}@example.com", password="wrong password 123").status_code
        for i in range(5)
    ]

    assert statuses == [401, 401, 401, 401, 429]


def test_successful_login_clears_pair_failures(client, alice, monkeypatch):
    monkeypatch.setenv(LOGIN_MAX_FAILURES_ENV_VAR, "3")
    reset_auth_limits()

    _login(client, password="wrong password 123")
    _login(client, password="wrong password 123")
    assert _login(client).status_code == 200

    _login(client, password="wrong password 123")
    _login(client, password="wrong password 123")
    assert _login(client).status_code == 200


class FakeMonotonic:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_rate_limiter_window_expiry():
    clock = FakeMonotonic()
    limiter = LoginRateLimiter(max_failures=2, window_seconds=60, clock=clock)

    limiter.record_failure("1.1.1.1", "a@x.com")
    limiter.record_failure("1.1.1.1", "a@x.com")
    assert limiter.retry_after("1.1.1.1", "a@x.com") == 60

    clock.now += 30
    assert limiter.retry_after("1.1.1.1", "a@x.com") == 30

    clock.now += 30
    assert limiter.retry_after("1.1.1.1", "a@x.com") is None
    assert limiter.retry_after("2.2.2.2", "b@x.com") is None


def test_rate_limiter_memory_is_bounded():
    limiter = LoginRateLimiter(max_failures=5, max_tracked_keys=50)

    for i in range(1000):
        limiter.record_failure(f"10.0.{i // 256}.{i % 256}", f"user{i}@x.com")

    assert limiter.tracked_keys() <= 50


def test_rate_limiter_per_key_history_is_bounded():
    limiter = LoginRateLimiter(max_failures=3, max_failures_per_ip=3, max_failures_per_email=3)

    for _ in range(1000):
        limiter.record_failure("1.1.1.1", "a@x.com")

    assert all(len(stamps) <= 3 for stamps in limiter._failures.values())


# =========================================================
# BOUNDED HASHING CONCURRENCY
# =========================================================


def test_password_work_limiter_never_exceeds_concurrency():
    limiter = PasswordWorkLimiter(max_concurrent=2, max_waiting=50, acquire_timeout=10)
    peak = []
    lock = threading.Lock()

    def work():
        with limiter.slot():
            with lock:
                peak.append(limiter.active)
            time.sleep(0.02)

    threads = [threading.Thread(target=work) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max(peak) <= 2
    assert limiter.active == 0 and limiter.waiting == 0


def test_password_work_limiter_times_out_and_rejects_full_queue():
    limiter = PasswordWorkLimiter(max_concurrent=1, max_waiting=1, acquire_timeout=0.2)
    release = threading.Event()
    held = threading.Event()

    def holder():
        with limiter.slot():
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(5)

    # One waiter allowed, but it times out.
    started = time.perf_counter()
    with pytest.raises(PasswordCapacityError):
        with limiter.slot():
            pass
    assert 0.15 <= time.perf_counter() - started < 2

    # With the single waiting place taken, the next caller fails fast.
    waiter_in_queue = threading.Event()

    def waiter():
        waiter_in_queue.set()
        try:
            with limiter.slot():
                pass
        except PasswordCapacityError:
            pass

    w = threading.Thread(target=waiter)
    w.start()
    waiter_in_queue.wait(5)
    deadline = time.time() + 2
    while limiter.waiting < 1 and time.time() < deadline:
        time.sleep(0.005)

    started = time.perf_counter()
    with pytest.raises(PasswordCapacityError):
        with limiter.slot():
            pass
    assert time.perf_counter() - started < 0.1

    release.set()
    t.join()
    w.join()
    assert limiter.active == 0 and limiter.waiting == 0


def test_saturated_hashing_returns_503_for_login_and_register(client, alice, monkeypatch):
    saturated = PasswordWorkLimiter(max_concurrent=1, max_waiting=0, acquire_timeout=0.05)
    monkeypatch.setattr(routes_module, "get_password_work_limiter", lambda: saturated)

    with saturated.slot():  # occupy the only slot
        login = _login(client)
        register = _register(client, email="new@example.com")

    for response in (login, register):
        assert response.status_code == 503
        assert response.json() == {"detail": "Authentication is busy. Please retry shortly."}
    assert "set-cookie" not in login.headers


def test_default_limiter_allows_two_concurrent_hashes(monkeypatch):
    for name in (
        limits_module.HASH_CONCURRENCY_ENV_VAR,
        limits_module.HASH_MAX_WAITING_ENV_VAR,
        limits_module.HASH_WAIT_SECONDS_ENV_VAR,
    ):
        monkeypatch.delenv(name, raising=False)
    reset_auth_limits()

    limiter = limits_module.get_password_work_limiter()

    assert limiter.max_concurrent == 2
    assert limiter.max_waiting == 8
    assert limiter.acquire_timeout == 5.0


# =========================================================
# ORIGIN / CSRF
# =========================================================


@pytest.mark.parametrize("path", ["/api/auth/register", "/api/auth/login", "/api/auth/logout"])
@pytest.mark.parametrize("origin", [None, "https://evil.example", "null", "http://localhost:5173.evil.example"])
def test_unsafe_auth_requests_require_trusted_origin(client, alice, path, origin):
    headers = {} if origin is None else {"Origin": origin}

    response = client.post(path, json={"email": EMAIL, "password": PASSWORD}, headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Untrusted request origin."}
    assert "set-cookie" not in response.headers


def test_untrusted_origin_cannot_log_out_a_session(client, alice, db_path):
    _login(client)
    token = client.cookies.get(DEFAULT_COOKIE_NAME)

    client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})

    assert SessionService(db_path).validate_session(token) is not None


def test_cors_configuration_unchanged(client):
    allowed = client.options(
        "/api/auth/login",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert allowed.headers.get("access-control-allow-origin") == ORIGIN
    assert allowed.headers.get("access-control-allow-credentials") == "true"

    denied = client.options(
        "/api/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert denied.headers.get("access-control-allow-origin") is None


# =========================================================
# DATABASE FAILURES
# =========================================================


def test_unavailable_database_returns_503(client, monkeypatch, tmp_path):
    unopenable = tmp_path / "is_a_directory"
    unopenable.mkdir()
    monkeypatch.setenv(AUTH_DB_PATH_ENV_VAR, str(unopenable))

    for response in (_register(client), _login(client)):
        assert response.status_code == 503
        assert response.json() == {"detail": "Authentication is temporarily unavailable."}
        assert "is_a_directory" not in response.text


def test_session_creation_failure_returns_503_without_cookie(client, alice, monkeypatch):
    def broken(self, user_id):
        raise SessionStoreError("Could not create session.")

    monkeypatch.setattr(SessionService, "create_session", broken)

    response = _login(client)

    assert response.status_code == 503
    assert "set-cookie" not in response.headers


# =========================================================
# NO SECRETS IN LOGS
# =========================================================


def test_passwords_and_tokens_never_logged(client, caplog, monkeypatch):
    monkeypatch.setenv(LOGIN_MAX_FAILURES_ENV_VAR, "2")
    reset_auth_limits()

    with caplog.at_level(logging.DEBUG):
        _register(client)
        _login(client, password="wrong password 999")
        _login(client)
        token = client.cookies.get(DEFAULT_COOKIE_NAME)
        client.get("/api/auth/me")
        client.post("/api/auth/logout", headers=HEADERS)

    assert PASSWORD not in caplog.text
    assert "wrong password 999" not in caplog.text
    assert token and token not in caplog.text
    assert "scrypt$" not in caplog.text
