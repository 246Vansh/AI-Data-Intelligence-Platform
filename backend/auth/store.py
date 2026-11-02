"""
Auth Step 1: SQLite-backed credential store (users only).

Holds the minimal users table real authentication needs. Sessions,
login and registration endpoints come in later steps and are
deliberately absent here; nothing in the API imports this module yet.

Design notes:
- One short-lived sqlite3 connection per operation, always closed, so
  the store is safe to share across FastAPI's threadpool workers
  without sharing a connection between threads.
- Every statement is parameterized.
- Only scrypt hashes from backend.auth.passwords are stored, never a
  plaintext password; the hash is excluded from UserRecord's repr so it
  cannot leak through logs or tracebacks.
- The database path is read when a store is constructed (not at import
  time), from AUTH_DB_PATH, defaulting to data/auth.db - matching the
  per-call env-var pattern used elsewhere (e.g. DEV_USER_ID).
"""

import os
import sqlite3
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Optional

from backend.auth.passwords import hash_password


AUTH_DB_PATH_ENV_VAR = "AUTH_DB_PATH"
DEFAULT_AUTH_DB_PATH = os.path.join("data", "auth.db")

MAX_EMAIL_LENGTH = 254

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


class InvalidEmailError(ValueError):
    """The email address is empty, too long or not plausibly an address."""


class DuplicateEmailError(ValueError):
    """A user with this (normalized) email already exists."""


@dataclass(frozen=True)
class UserRecord:
    id: str
    email: str
    created_at: str
    password_hash: str = field(repr=False)


def normalize_email(email: object) -> str:
    """
    Canonical form used for storage, uniqueness and lookup: surrounding
    whitespace stripped and the whole address lower-cased.

    Raises InvalidEmailError unless the result has exactly one "@" with
    a non-empty local part and domain, no whitespace, and at most 254
    characters. This is a sanity check, not full RFC 5322 validation.
    """

    if not isinstance(email, str):
        raise InvalidEmailError("Email must be a string.")

    normalized = email.strip().lower()

    if not normalized or len(normalized) > MAX_EMAIL_LENGTH:
        raise InvalidEmailError("Email must be between 1 and 254 characters.")

    if any(ch.isspace() for ch in normalized):
        raise InvalidEmailError("Email must not contain whitespace.")

    local, sep, domain = normalized.partition("@")
    if not sep or not local or not domain or "@" in domain:
        raise InvalidEmailError("Email must contain a single '@' with text on both sides.")

    return normalized


def _read_auth_db_path() -> str:
    return os.environ.get(AUTH_DB_PATH_ENV_VAR) or DEFAULT_AUTH_DB_PATH


class CredentialStore:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or _read_auth_db_path()

        parent = os.path.dirname(os.path.abspath(self._db_path))
        os.makedirs(parent, exist_ok=True)

        self._initialize_schema()

    @property
    def db_path(self) -> str:
        return self._db_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """
        Yield a fresh connection inside a transaction: committed on
        success, rolled back on error, and closed either way.
        """

        with closing(sqlite3.connect(self._db_path, timeout=10.0)) as connection:
            with connection:
                yield connection

    def _initialize_schema(self) -> None:
        # Idempotent: safe for every store instance and every restart.
        with self._connect() as connection:
            connection.execute(_SCHEMA)

    @staticmethod
    def _row_to_record(row) -> UserRecord:
        user_id, email, password_hash, created_at = row
        return UserRecord(
            id=user_id,
            email=email,
            created_at=created_at,
            password_hash=password_hash,
        )

    def create_user(self, email: str, password: str) -> UserRecord:
        """
        Create a user and return its record.

        Raises InvalidEmailError, PasswordPolicyError (from hashing), or
        DuplicateEmailError if the normalized email is already taken.
        The password is hashed before anything touches the database.
        """

        normalized = normalize_email(email)
        password_hash = hash_password(password)

        record = UserRecord(
            id=str(uuid.uuid4()),
            email=normalized,
            created_at=datetime.now(timezone.utc).isoformat(),
            password_hash=password_hash,
        )

        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO users (id, email, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (record.id, record.email, record.password_hash, record.created_at),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateEmailError("A user with this email already exists.") from exc

        return record

    def get_user_by_email(self, email: str) -> Optional[UserRecord]:
        """Look up by normalized email; None if absent or not a valid email."""

        try:
            normalized = normalize_email(email)
        except InvalidEmailError:
            return None

        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, password_hash, created_at FROM users WHERE email = ?",
                (normalized,),
            ).fetchone()

        return self._row_to_record(row) if row else None

    def get_user_by_id(self, user_id: str) -> Optional[UserRecord]:
        """Look up by id; None if absent."""

        if not isinstance(user_id, str) or not user_id:
            return None

        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, email, password_hash, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

        return self._row_to_record(row) if row else None
