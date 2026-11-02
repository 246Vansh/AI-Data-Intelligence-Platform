"""
Auth Step 1: standalone credential primitives (password hashing and a
SQLite user store). Not yet wired into any route or dependency -
backend.dependencies.get_current_user() is unchanged.
"""

from backend.auth.passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    is_supported_hash,
    validate_password_policy,
    verify_password,
)
from backend.auth.sessions import (
    DEFAULT_ABSOLUTE_LIFETIME,
    DEFAULT_IDLE_TIMEOUT,
    NewSession,
    SessionError,
    SessionInfo,
    SessionService,
    SessionStoreError,
    UnknownUserError,
)
from backend.auth.store import (
    AUTH_DB_PATH_ENV_VAR,
    DEFAULT_AUTH_DB_PATH,
    CredentialStore,
    DuplicateEmailError,
    InvalidEmailError,
    UserRecord,
    normalize_email,
)

__all__ = [
    "AUTH_DB_PATH_ENV_VAR",
    "DEFAULT_ABSOLUTE_LIFETIME",
    "DEFAULT_AUTH_DB_PATH",
    "DEFAULT_IDLE_TIMEOUT",
    "NewSession",
    "SessionError",
    "SessionInfo",
    "SessionService",
    "SessionStoreError",
    "UnknownUserError",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "CredentialStore",
    "DuplicateEmailError",
    "InvalidEmailError",
    "PasswordPolicyError",
    "UserRecord",
    "hash_password",
    "is_supported_hash",
    "normalize_email",
    "validate_password_policy",
    "verify_password",
]
