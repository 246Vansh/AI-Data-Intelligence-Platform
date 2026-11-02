"""
Auth Step 2: SQLite-backed server-side sessions.

Lives in the same database as the Step 1 users table
(backend.auth.store), adding a `sessions` table next to it. Not yet
wired into any route, dependency or cookie - that is Step 3.

Design notes:
- Opaque bearer tokens from secrets.token_urlsafe(32) (256 bits). Only
  the SHA-256 hex digest is stored; the raw token is returned exactly
  once, from create_session(), and never logged or persisted.
- A session ends at whichever comes first:
    * idle timeout     - no successful validation for `idle_timeout`
                         (default 2 hours), measured from last_seen_at;
    * absolute lifetime - `absolute_lifetime` after creation (default
                         7 days), fixed in expires_at at creation and
                         never moved by activity.
- validate_session() bumps last_seen_at only, inside a single
  BEGIN IMMEDIATE transaction with the expiry check, so a concurrent
  revoke cannot interleave between read and write.
- A session cannot outlive its user: sessions.user_id references
  users(id) ON DELETE CASCADE with PRAGMA foreign_keys=ON on every
  connection this module opens, and validation additionally joins on
  users so a user removed through any other connection still
  invalidates their sessions.
- Validation fails closed: a database error yields None (logged by
  exception type only, never with token material).
- Timestamps are UTC-aware datetimes, stored as fixed-width ISO 8601
  strings (always with microseconds and +00:00), so SQL string
  comparison in cleanup orders them correctly.
"""

import hashlib
import logging
import os
import secrets
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator, Optional

from backend.auth.store import CredentialStore, _read_auth_db_path


logger = logging.getLogger(__name__)


SESSION_IDLE_TIMEOUT_ENV_VAR = "AUTH_SESSION_IDLE_TIMEOUT_SECONDS"
SESSION_ABSOLUTE_LIFETIME_ENV_VAR = "AUTH_SESSION_ABSOLUTE_LIFETIME_SECONDS"

DEFAULT_IDLE_TIMEOUT = timedelta(hours=2)
DEFAULT_ABSOLUTE_LIFETIME = timedelta(days=7)

TOKEN_BYTES = 32

# token_urlsafe(32) yields 43 chars; anything far longer is not a token
# this service issued and is rejected before hashing.
_MAX_TOKEN_LENGTH = 512

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
"""

_INDEX = "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id)"


class SessionError(RuntimeError):
    """Base class for session-service failures."""


class UnknownUserError(SessionError):
    """create_session() was asked for a user that does not exist."""


class SessionStoreError(SessionError):
    """The session database could not complete the operation."""


@dataclass(frozen=True)
class SessionInfo:
    user_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class NewSession:
    """Returned once by create_session(); the only place a raw token exists."""

    token: str = field(repr=False)
    session: SessionInfo


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a raw session token - the only stored form."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Session timestamp is not timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _read_positive_seconds_env(name: str, default: timedelta) -> timedelta:
    try:
        seconds = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return timedelta(seconds=seconds) if seconds > 0 else default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionService:
    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        idle_timeout: Optional[timedelta] = None,
        absolute_lifetime: Optional[timedelta] = None,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self._db_path = db_path or _read_auth_db_path()

        self._idle_timeout = idle_timeout or _read_positive_seconds_env(
            SESSION_IDLE_TIMEOUT_ENV_VAR, DEFAULT_IDLE_TIMEOUT
        )
        self._absolute_lifetime = absolute_lifetime or _read_positive_seconds_env(
            SESSION_ABSOLUTE_LIFETIME_ENV_VAR, DEFAULT_ABSOLUTE_LIFETIME
        )
        if self._idle_timeout <= timedelta(0) or self._absolute_lifetime <= timedelta(0):
            raise ValueError("Session timeouts must be positive.")

        self._clock = clock

        # Ensure the users table the FK references exists (idempotent,
        # never touches existing rows), then add the sessions table.
        CredentialStore(self._db_path)
        with self._connect() as connection:
            connection.execute(_SCHEMA)
            connection.execute(_INDEX)

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def idle_timeout(self) -> timedelta:
        return self._idle_timeout

    @property
    def absolute_lifetime(self) -> timedelta:
        return self._absolute_lifetime

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("Session clock must return timezone-aware datetimes.")
        return now.astimezone(timezone.utc)

    @contextmanager
    def _connect(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """
        Fresh connection with foreign keys enforced, inside a
        transaction (committed on success, rolled back on error), always
        closed. `immediate` takes the write lock up front so a
        read-then-write sequence is atomic.
        """

        with closing(sqlite3.connect(self._db_path, timeout=10.0)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                if immediate:
                    connection.execute("BEGIN IMMEDIATE")
                yield connection

    # -----------------------------------------------------
    # lifecycle
    # -----------------------------------------------------

    def create_session(self, user_id: str) -> NewSession:
        """
        Create a session for an existing user and return the raw token
        (once) with its metadata. Raises UnknownUserError if the user
        does not exist, SessionStoreError on a database failure.
        """

        if not isinstance(user_id, str) or not user_id:
            raise UnknownUserError("Cannot create a session for an unknown user.")

        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = self._now()
        info = SessionInfo(
            user_id=user_id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + self._absolute_lifetime,
        )

        try:
            with self._connect(immediate=True) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM users WHERE id = ?", (user_id,)
                ).fetchone()
                if exists is None:
                    raise UnknownUserError("Cannot create a session for an unknown user.")

                connection.execute(
                    "INSERT INTO sessions "
                    "(token_hash, user_id, created_at, last_seen_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        hash_token(token),
                        user_id,
                        _format_ts(info.created_at),
                        _format_ts(info.last_seen_at),
                        _format_ts(info.expires_at),
                    ),
                )
        except sqlite3.Error as exc:
            logger.warning("Session creation failed: %s", type(exc).__name__)
            raise SessionStoreError("Could not create session.") from exc

        return NewSession(token=token, session=info)

    def validate_session(self, token: object) -> Optional[SessionInfo]:
        """
        Return the live session for `token`, refreshing last_seen_at, or
        None if the token is unknown, revoked, idle-expired, past its
        absolute lifetime, belongs to a deleted user, or the database
        fails. Expired/orphaned rows found here are deleted. Never
        extends expires_at.
        """

        if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
            return None

        token_hash = hash_token(token)

        try:
            now = self._now()
            with self._connect(immediate=True) as connection:
                row = connection.execute(
                    "SELECT s.user_id, s.created_at, s.last_seen_at, s.expires_at "
                    "FROM sessions s JOIN users u ON u.id = s.user_id "
                    "WHERE s.token_hash = ?",
                    (token_hash,),
                ).fetchone()

                if row is None:
                    # Unknown, revoked, or orphaned by a user deleted
                    # through a connection without FK enforcement.
                    connection.execute(
                        "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
                    )
                    return None

                user_id, created_raw, last_seen_raw, expires_raw = row

                try:
                    created_at = _parse_ts(created_raw)
                    last_seen_at = _parse_ts(last_seen_raw)
                    expires_at = _parse_ts(expires_raw)
                except (TypeError, ValueError):
                    connection.execute(
                        "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
                    )
                    return None

                if now >= expires_at or now >= last_seen_at + self._idle_timeout:
                    connection.execute(
                        "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
                    )
                    return None

                # Only ever move last_seen_at forward; expires_at is
                # deliberately not touched.
                if now > last_seen_at:
                    connection.execute(
                        "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
                        (_format_ts(now), token_hash),
                    )
                    last_seen_at = now

        except sqlite3.Error as exc:
            logger.warning("Session validation failed closed: %s", type(exc).__name__)
            return None

        return SessionInfo(
            user_id=user_id,
            created_at=created_at,
            last_seen_at=last_seen_at,
            expires_at=expires_at,
        )

    def revoke_session(self, token: object) -> bool:
        """
        Delete the session for `token`. Returns True if one existed.
        Raises SessionStoreError on a database failure, so a logout
        that did not take effect is never reported as successful.
        """

        if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
            return False

        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM sessions WHERE token_hash = ?", (hash_token(token),)
                )
        except sqlite3.Error as exc:
            logger.warning("Session revocation failed: %s", type(exc).__name__)
            raise SessionStoreError("Could not revoke session.") from exc

        return cursor.rowcount > 0

    def revoke_all_sessions(self, user_id: str) -> int:
        """Delete every session belonging to `user_id`; returns the count."""

        if not isinstance(user_id, str) or not user_id:
            return 0

        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM sessions WHERE user_id = ?", (user_id,)
                )
        except sqlite3.Error as exc:
            logger.warning("Bulk session revocation failed: %s", type(exc).__name__)
            raise SessionStoreError("Could not revoke sessions.") from exc

        return cursor.rowcount

    def cleanup_expired_sessions(self) -> int:
        """
        Delete sessions past their absolute lifetime, idle past the
        idle timeout, or whose user no longer exists. Returns the
        number removed.
        """

        now = self._now()
        idle_cutoff = now - self._idle_timeout

        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM sessions "
                    "WHERE expires_at <= ? "
                    "OR last_seen_at <= ? "
                    "OR user_id NOT IN (SELECT id FROM users)",
                    (_format_ts(now), _format_ts(idle_cutoff)),
                )
        except sqlite3.Error as exc:
            logger.warning("Session cleanup failed: %s", type(exc).__name__)
            raise SessionStoreError("Could not clean up sessions.") from exc

        return cursor.rowcount
