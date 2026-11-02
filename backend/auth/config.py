"""
Auth Step 3: centralized authentication settings.

Everything is read from the environment per call to load_auth_settings()
(never at import time) - matching DEV_USER_ID's original behavior and
avoiding the known trap where .env is loaded after a module captured
its values.

Environment variables (all optional):

  AUTH_COOKIE_NAME        session cookie name            default "aidi_session"
  AUTH_COOKIE_SECURE      Secure flag ("0"/"false" off)  default ON
  AUTH_COOKIE_SAMESITE    "strict" or "lax"              default "strict"
  AUTH_DEV_MODE           explicit dev identity bypass   default OFF
  DEV_USER_ID             identity used in dev mode      default "dev-user"
  AUTH_ALLOW_REGISTRATION open self-registration         default OFF
  AUTH_DB_PATH            see backend.auth.store
  AUTH_SESSION_*_SECONDS  see backend.auth.sessions

HttpOnly is not configurable - it is always on.

Development bypass guard: AUTH_DEV_MODE is honoured ONLY when the
Secure cookie flag is explicitly turned off. Secure is on by default and
must be on for any HTTPS/production deployment, so a production config
can never silently run with the bypass - if both are set, the bypass is
refused (and an error is logged) and real cookie authentication applies.
"""

import logging
import os
import threading
from dataclasses import dataclass
from datetime import timedelta

from backend.auth.sessions import (
    DEFAULT_ABSOLUTE_LIFETIME,
    DEFAULT_IDLE_TIMEOUT,
    SESSION_ABSOLUTE_LIFETIME_ENV_VAR,
    SESSION_IDLE_TIMEOUT_ENV_VAR,
    _read_positive_seconds_env,
)
from backend.auth.store import _read_auth_db_path


logger = logging.getLogger(__name__)


AUTH_COOKIE_NAME_ENV_VAR = "AUTH_COOKIE_NAME"
AUTH_COOKIE_SECURE_ENV_VAR = "AUTH_COOKIE_SECURE"
AUTH_COOKIE_SAMESITE_ENV_VAR = "AUTH_COOKIE_SAMESITE"
AUTH_DEV_MODE_ENV_VAR = "AUTH_DEV_MODE"
DEV_USER_ID_ENV_VAR = "DEV_USER_ID"
AUTH_ALLOW_REGISTRATION_ENV_VAR = "AUTH_ALLOW_REGISTRATION"

DEFAULT_COOKIE_NAME = "aidi_session"
DEFAULT_COOKIE_SAMESITE = "strict"
DEFAULT_DEV_USER_ID = "dev-user"

# "none" is deliberately unsupported: it would send the session cookie
# on cross-site requests, which the planned CSRF posture relies on not
# happening.
_ALLOWED_SAMESITE = ("strict", "lax")

# Settings are loaded per request, so the misconfiguration error is
# emitted once per process rather than on every call.
_refusal_logged = threading.Event()

_TRUE_VALUES = ("1", "true", "yes", "on")
_FALSE_VALUES = ("0", "false", "no", "off")


@dataclass(frozen=True)
class AuthSettings:
    cookie_name: str
    cookie_secure: bool
    cookie_samesite: str
    dev_mode: bool
    dev_user_id: str
    allow_registration: bool
    db_path: str
    idle_timeout: timedelta
    absolute_lifetime: timedelta

    # Fixed, not configurable.
    cookie_httponly: bool = True
    cookie_path: str = "/"

    def cookie_kwargs(self) -> dict:
        """
        Keyword arguments for Response.set_cookie() (used from Step 4).
        max_age matches the absolute lifetime; the server-side session
        enforces idle expiry independently.
        """

        return {
            "key": self.cookie_name,
            "httponly": self.cookie_httponly,
            "secure": self.cookie_secure,
            "samesite": self.cookie_samesite,
            "path": self.cookie_path,
            "max_age": int(self.absolute_lifetime.total_seconds()),
        }


def _read_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return default


def load_auth_settings() -> AuthSettings:
    cookie_name = os.environ.get(AUTH_COOKIE_NAME_ENV_VAR, "").strip() or DEFAULT_COOKIE_NAME

    samesite = os.environ.get(AUTH_COOKIE_SAMESITE_ENV_VAR, "").strip().lower()
    if samesite not in _ALLOWED_SAMESITE:
        samesite = DEFAULT_COOKIE_SAMESITE

    cookie_secure = _read_flag(AUTH_COOKIE_SECURE_ENV_VAR, default=True)

    dev_mode_requested = _read_flag(AUTH_DEV_MODE_ENV_VAR, default=False)
    dev_mode = dev_mode_requested and not cookie_secure
    if dev_mode_requested and cookie_secure and not _refusal_logged.is_set():
        _refusal_logged.set()
        logger.error(
            "%s is set but ignored because %s is enabled (production "
            "configuration); real session authentication is enforced.",
            AUTH_DEV_MODE_ENV_VAR,
            AUTH_COOKIE_SECURE_ENV_VAR,
        )

    return AuthSettings(
        cookie_name=cookie_name,
        cookie_secure=cookie_secure,
        cookie_samesite=samesite,
        dev_mode=dev_mode,
        dev_user_id=os.environ.get(DEV_USER_ID_ENV_VAR, "").strip() or DEFAULT_DEV_USER_ID,
        allow_registration=_read_flag(AUTH_ALLOW_REGISTRATION_ENV_VAR, default=False),
        db_path=_read_auth_db_path(),
        idle_timeout=_read_positive_seconds_env(
            SESSION_IDLE_TIMEOUT_ENV_VAR, DEFAULT_IDLE_TIMEOUT
        ),
        absolute_lifetime=_read_positive_seconds_env(
            SESSION_ABSOLUTE_LIFETIME_ENV_VAR, DEFAULT_ABSOLUTE_LIFETIME
        ),
    )
