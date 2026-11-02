"""
Auth Step 4: registration, login, logout and current-user endpoints.

Built only from the existing pieces: CredentialStore (users),
SessionService (sessions), load_auth_settings() (cookie policy) and
get_current_user() (the API's single authentication boundary).

Request handling notes:
- Unsafe endpoints (register/login/logout) first require a trusted
  Origin header from backend.cors.ALLOWED_ORIGINS (CSRF defence on top
  of SameSite=Strict). A missing or untrusted Origin is a 403.
- Bodies are read here, capped at 4 KiB, and validated by hand rather
  than through a Pydantic model, because FastAPI's 422 responses echo
  the offending input - which for these endpoints would be a password.
- scrypt work runs on the threadpool under PasswordWorkLimiter, so the
  event loop never blocks and peak hashing memory stays bounded.
- Nothing here logs emails, passwords, tokens, cookies or hashes;
  failures are logged by exception type only.
"""

import json
import logging
import sqlite3
import threading
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from backend.auth.config import AuthSettings, load_auth_settings
from backend.auth.limits import (
    PasswordCapacityError,
    get_login_rate_limiter,
    get_password_work_limiter,
)
from backend.auth.passwords import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
    verify_password,
)
from backend.auth.sessions import SessionError
from backend.auth.store import (
    MAX_EMAIL_LENGTH,
    CredentialStore,
    DuplicateEmailError,
    InvalidEmailError,
    UserRecord,
    normalize_email,
)
from backend.cors import ALLOWED_ORIGINS
from backend.dependencies import (
    AuthenticatedUser,
    get_current_user,
    get_session_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/auth", tags=["auth"])


MAX_AUTH_BODY_BYTES = 4096

INVALID_CREDENTIALS = "Invalid email or password."
UNAVAILABLE = "Authentication is temporarily unavailable."
BUSY = "Authentication is busy. Please retry shortly."


# =========================================================
# helpers
# =========================================================


_credential_stores: dict[str, CredentialStore] = {}
_credential_stores_lock = threading.Lock()


def get_credential_store(settings: AuthSettings) -> CredentialStore:
    with _credential_stores_lock:
        store = _credential_stores.get(settings.db_path)
        if store is None:
            store = CredentialStore(settings.db_path)
            _credential_stores[settings.db_path] = store
        return store


_dummy_hash: Optional[str] = None
_dummy_hash_lock = threading.Lock()


def _get_dummy_hash() -> str:
    """
    A real scrypt hash of a random-looking constant, verified against
    when the email is unknown so that path costs the same scrypt work as
    a wrong password for a real account. Computed once, lazily (callers
    hold a PasswordWorkLimiter slot).
    """

    global _dummy_hash

    with _dummy_hash_lock:
        if _dummy_hash is None:
            _dummy_hash = hash_password("timing-equalizer-not-a-real-password")
        return _dummy_hash


def _unavailable(exc: BaseException) -> HTTPException:
    logger.warning("Auth storage failure: %s", type(exc).__name__)
    return HTTPException(status_code=503, detail=UNAVAILABLE)


def require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin or origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Untrusted request origin.")


async def _read_json_object(request: Request) -> dict[str, Any]:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_AUTH_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Request body too large.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid request body.") from None

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_AUTH_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body too large.")

    try:
        payload = json.loads(bytes(body))
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Request body must be JSON.") from None

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object.")

    return payload


def _credentials_from(payload: dict[str, Any]) -> tuple[str, str]:
    email = payload.get("email")
    password = payload.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        raise HTTPException(status_code=400, detail="Email and password are required.")
    return email, password


def _public_user(user: UserRecord) -> dict[str, Any]:
    # Explicit allow-list: never the password hash.
    return {"id": user.id, "email": user.email, "created_at": user.created_at}


def _client_ip(request: Request) -> str:
    # The direct peer only. X-Forwarded-For is not trusted: there is no
    # trusted proxy configuration, and a client could forge it to dodge
    # per-IP limits.
    return request.client.host if request.client else "unknown"


def _clear_session_cookie(response: JSONResponse, settings: AuthSettings) -> None:
    response.delete_cookie(
        key=settings.cookie_name,
        path=settings.cookie_path,
        secure=settings.cookie_secure,
        httponly=settings.cookie_httponly,
        samesite=settings.cookie_samesite,
    )


# =========================================================
# register
# =========================================================


def _register_blocking(settings: AuthSettings, email: str, password: str) -> UserRecord:
    try:
        with get_password_work_limiter().slot():
            return get_credential_store(settings).create_user(email, password)
    except PasswordCapacityError:
        raise HTTPException(status_code=503, detail=BUSY) from None
    except DuplicateEmailError:
        raise HTTPException(
            status_code=409, detail="An account with this email already exists."
        ) from None
    except (sqlite3.Error, OSError) as exc:
        raise _unavailable(exc) from None


@router.post("/register", status_code=201, dependencies=[Depends(require_trusted_origin)])
async def register(request: Request):
    settings = load_auth_settings()

    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail="Registration is disabled.")

    email, password = _credentials_from(await _read_json_object(request))

    try:
        normalize_email(email)
        validate_password_policy(password)
    except (InvalidEmailError, PasswordPolicyError) as exc:
        # Both messages are fixed policy text - never the input itself.
        raise HTTPException(status_code=400, detail=str(exc)) from None

    user = await run_in_threadpool(_register_blocking, settings, email, password)

    return {"user": _public_user(user)}


# =========================================================
# login
# =========================================================


def _login_blocking(
    settings: AuthSettings,
    email: str,
    password: str,
    ip: str,
    previous_token: Optional[str],
):
    limiter = get_login_rate_limiter()

    try:
        rate_key_email = normalize_email(email)
    except InvalidEmailError:
        rate_key_email = email.strip().lower()[:MAX_EMAIL_LENGTH]
        email_valid = False
    else:
        email_valid = True

    retry_after = limiter.retry_after(ip, rate_key_email)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    try:
        user = get_credential_store(settings).get_user_by_email(email) if email_valid else None

        with get_password_work_limiter().slot():
            if user is not None:
                verified = verify_password(password, user.password_hash)
            else:
                # Same scrypt cost as a wrong password for a real user.
                verify_password(password, _get_dummy_hash())
                verified = False

    except PasswordCapacityError:
        raise HTTPException(status_code=503, detail=BUSY) from None
    except (sqlite3.Error, OSError) as exc:
        raise _unavailable(exc) from None

    if not verified:
        limiter.record_failure(ip, rate_key_email)
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)

    limiter.record_success(ip, rate_key_email)

    sessions = get_session_service(settings)

    # Never reuse a client-supplied token: retire any session the
    # browser already holds, then always issue a brand-new one.
    if previous_token:
        try:
            sessions.revoke_session(previous_token)
        except SessionError:
            pass

    try:
        new_session = sessions.create_session(user.id)
    except SessionError as exc:
        raise _unavailable(exc) from None

    return user, new_session


@router.post("/login", dependencies=[Depends(require_trusted_origin)])
async def login(request: Request):
    settings = load_auth_settings()
    email, password = _credentials_from(await _read_json_object(request))

    user, new_session = await run_in_threadpool(
        _login_blocking,
        settings,
        email,
        password,
        _client_ip(request),
        request.cookies.get(settings.cookie_name),
    )

    response = JSONResponse({"user": _public_user(user)})
    response.set_cookie(value=new_session.token, **settings.cookie_kwargs())
    return response


# =========================================================
# logout
# =========================================================


@router.post("/logout", dependencies=[Depends(require_trusted_origin)])
def logout(request: Request):
    settings = load_auth_settings()
    token = request.cookies.get(settings.cookie_name)

    revoked_ok = True
    if token:
        try:
            get_session_service(settings).revoke_session(token)
        except (SessionError, sqlite3.Error, OSError) as exc:
            logger.warning("Logout revocation failed: %s", type(exc).__name__)
            revoked_ok = False

    if revoked_ok:
        response = JSONResponse({"status": "logged_out"})
    else:
        # Still clear the browser cookie, but never claim the server-side
        # session is gone when it may not be.
        response = JSONResponse({"detail": UNAVAILABLE}, status_code=503)

    _clear_session_cookie(response, settings)
    return response


# =========================================================
# me
# =========================================================


@router.get("/me")
def me(user: AuthenticatedUser = Depends(get_current_user)):
    settings = load_auth_settings()

    if settings.dev_mode:
        return {"user": {"id": user.user_id, "email": None, "created_at": None}, "dev_mode": True}

    try:
        record = get_credential_store(settings).get_user_by_id(user.user_id)
    except (sqlite3.Error, OSError) as exc:
        raise _unavailable(exc) from None

    if record is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    return {"user": _public_user(record), "dev_mode": False}
