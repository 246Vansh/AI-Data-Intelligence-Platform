"""
Auth Step 4: process-local resource and abuse limits for the auth
endpoints. Pure Python, no FastAPI imports, so each piece is testable
on its own.

IMPORTANT - single-process only. Both limiters keep their state in this
process's memory. Behind several worker processes or hosts, each one
enforces its own limits independently (so the effective failed-login
threshold multiplies by the worker count) and nothing is shared or
persisted across restarts. A multi-process deployment needs a shared
store (e.g. Redis) instead; uvicorn's default single worker is fine.

PasswordWorkLimiter
    scrypt costs ~128 MiB and ~0.5s per hash (backend.auth.passwords).
    At most `max_concurrent` (default 2) hash/verify operations run at
    once; at most `max_waiting` (default 8) more may wait, each for at
    most `acquire_timeout` seconds (default 5). Anything beyond that
    fails fast with PasswordCapacityError -> HTTP 503. Peak scrypt
    memory is therefore bounded at max_concurrent x 128 MiB, and no
    request can wait indefinitely.

LoginRateLimiter
    Sliding-window failed-login counter over three scopes:
      - (client IP, normalized email)  default 5 failures
      - client IP                      default 20 failures
      - normalized email               default 50 failures
    within `window_seconds` (default 15 min). Any scope at its limit
    blocks further attempts (HTTP 429) until its oldest failure ages
    out. Failures are counted identically for existing and unknown
    emails, so a 429 never reveals whether an account exists. The
    per-email threshold is deliberately high: it slows distributed
    guessing against one account without letting a single attacker
    cheaply lock a real user out. Memory is bounded: at most
    `max_tracked_keys` keys (LRU eviction), each holding at most its
    scope's threshold of timestamps.
"""

import math
import os
import threading
import time
from collections import OrderedDict, deque
from contextlib import contextmanager
from typing import Callable, Iterator, Optional


HASH_CONCURRENCY_ENV_VAR = "AUTH_PASSWORD_HASH_CONCURRENCY"
HASH_MAX_WAITING_ENV_VAR = "AUTH_PASSWORD_HASH_MAX_WAITING"
HASH_WAIT_SECONDS_ENV_VAR = "AUTH_PASSWORD_HASH_WAIT_SECONDS"

LOGIN_MAX_FAILURES_ENV_VAR = "AUTH_LOGIN_MAX_FAILURES"
LOGIN_MAX_FAILURES_PER_IP_ENV_VAR = "AUTH_LOGIN_MAX_FAILURES_PER_IP"
LOGIN_MAX_FAILURES_PER_EMAIL_ENV_VAR = "AUTH_LOGIN_MAX_FAILURES_PER_EMAIL"
LOGIN_WINDOW_SECONDS_ENV_VAR = "AUTH_LOGIN_FAILURE_WINDOW_SECONDS"

DEFAULT_HASH_CONCURRENCY = 2
DEFAULT_HASH_MAX_WAITING = 8
DEFAULT_HASH_WAIT_SECONDS = 5.0

DEFAULT_LOGIN_MAX_FAILURES = 5
DEFAULT_LOGIN_MAX_FAILURES_PER_IP = 20
DEFAULT_LOGIN_MAX_FAILURES_PER_EMAIL = 50
DEFAULT_LOGIN_WINDOW_SECONDS = 15 * 60
DEFAULT_MAX_TRACKED_KEYS = 10_000


class PasswordCapacityError(RuntimeError):
    """No password-hashing slot could be acquired promptly."""


class PasswordWorkLimiter:
    def __init__(
        self,
        max_concurrent: int = DEFAULT_HASH_CONCURRENCY,
        max_waiting: int = DEFAULT_HASH_MAX_WAITING,
        acquire_timeout: float = DEFAULT_HASH_WAIT_SECONDS,
    ):
        if max_concurrent < 1 or max_waiting < 0 or acquire_timeout < 0:
            raise ValueError("Invalid password work limits.")

        self.max_concurrent = max_concurrent
        self.max_waiting = max_waiting
        self.acquire_timeout = acquire_timeout

        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._lock = threading.Lock()
        self._waiting = 0
        self._active = 0

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    @property
    def waiting(self) -> int:
        with self._lock:
            return self._waiting

    @contextmanager
    def slot(self) -> Iterator[None]:
        """
        Hold one hashing slot for the duration of the block. Raises
        PasswordCapacityError immediately if the wait queue is full, or
        after `acquire_timeout` seconds without a free slot.
        """

        # Fast path: a free slot is taken without joining the queue.
        acquired = self._slots.acquire(blocking=False)

        if not acquired:
            with self._lock:
                if self._waiting >= self.max_waiting:
                    raise PasswordCapacityError("Password hashing capacity exhausted.")
                self._waiting += 1
            try:
                acquired = self._slots.acquire(timeout=self.acquire_timeout)
            finally:
                with self._lock:
                    self._waiting -= 1

            if not acquired:
                raise PasswordCapacityError("Password hashing capacity exhausted.")

        with self._lock:
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._slots.release()


class LoginRateLimiter:
    def __init__(
        self,
        *,
        max_failures: int = DEFAULT_LOGIN_MAX_FAILURES,
        max_failures_per_ip: int = DEFAULT_LOGIN_MAX_FAILURES_PER_IP,
        max_failures_per_email: int = DEFAULT_LOGIN_MAX_FAILURES_PER_EMAIL,
        window_seconds: float = DEFAULT_LOGIN_WINDOW_SECONDS,
        max_tracked_keys: int = DEFAULT_MAX_TRACKED_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ):
        limits = (max_failures, max_failures_per_ip, max_failures_per_email)
        if min(limits) < 1 or window_seconds <= 0 or max_tracked_keys < 1:
            raise ValueError("Invalid login rate limits.")

        self._thresholds = {
            "pair": max_failures,
            "ip": max_failures_per_ip,
            "email": max_failures_per_email,
        }
        self.window_seconds = window_seconds
        self.max_tracked_keys = max_tracked_keys
        self._clock = clock

        self._failures: "OrderedDict[tuple, deque]" = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _keys(ip: str, email: str) -> list[tuple]:
        return [("pair", ip, email), ("ip", ip), ("email", email)]

    def _prune(self, key: tuple, now: float) -> Optional[deque]:
        stamps = self._failures.get(key)
        if stamps is None:
            return None
        cutoff = now - self.window_seconds
        while stamps and stamps[0] <= cutoff:
            stamps.popleft()
        if not stamps:
            del self._failures[key]
            return None
        return stamps

    def retry_after(self, ip: str, email: str) -> Optional[int]:
        """
        Seconds until an attempt for (ip, email) is allowed again, or
        None if it is allowed now.
        """

        now = self._clock()
        wait = 0.0

        with self._lock:
            for key in self._keys(ip, email):
                stamps = self._prune(key, now)
                if stamps is not None and len(stamps) >= self._thresholds[key[0]]:
                    wait = max(wait, stamps[0] + self.window_seconds - now)

        return max(1, math.ceil(wait)) if wait > 0 else None

    def record_failure(self, ip: str, email: str) -> None:
        now = self._clock()

        with self._lock:
            for key in self._keys(ip, email):
                stamps = self._prune(key, now)
                if stamps is None:
                    # Bounded per key: only the most recent `threshold`
                    # timestamps can ever matter.
                    stamps = deque(maxlen=self._thresholds[key[0]])
                    self._failures[key] = stamps
                stamps.append(now)
                self._failures.move_to_end(key)

            while len(self._failures) > self.max_tracked_keys:
                self._failures.popitem(last=False)

    def record_success(self, ip: str, email: str) -> None:
        """A correct password clears the (ip, email) pair only."""

        with self._lock:
            self._failures.pop(("pair", ip, email), None)

    def tracked_keys(self) -> int:
        with self._lock:
            return len(self._failures)


# =========================================================
# Process-wide instances (created lazily from the environment).
# =========================================================


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


_instances_lock = threading.Lock()
_password_work_limiter: Optional[PasswordWorkLimiter] = None
_login_rate_limiter: Optional[LoginRateLimiter] = None


def get_password_work_limiter() -> PasswordWorkLimiter:
    global _password_work_limiter

    with _instances_lock:
        if _password_work_limiter is None:
            _password_work_limiter = PasswordWorkLimiter(
                max_concurrent=_env_int(HASH_CONCURRENCY_ENV_VAR, DEFAULT_HASH_CONCURRENCY),
                max_waiting=_env_int(HASH_MAX_WAITING_ENV_VAR, DEFAULT_HASH_MAX_WAITING),
                acquire_timeout=_env_float(HASH_WAIT_SECONDS_ENV_VAR, DEFAULT_HASH_WAIT_SECONDS),
            )
        return _password_work_limiter


def get_login_rate_limiter() -> LoginRateLimiter:
    global _login_rate_limiter

    with _instances_lock:
        if _login_rate_limiter is None:
            _login_rate_limiter = LoginRateLimiter(
                max_failures=_env_int(LOGIN_MAX_FAILURES_ENV_VAR, DEFAULT_LOGIN_MAX_FAILURES),
                max_failures_per_ip=_env_int(
                    LOGIN_MAX_FAILURES_PER_IP_ENV_VAR, DEFAULT_LOGIN_MAX_FAILURES_PER_IP
                ),
                max_failures_per_email=_env_int(
                    LOGIN_MAX_FAILURES_PER_EMAIL_ENV_VAR, DEFAULT_LOGIN_MAX_FAILURES_PER_EMAIL
                ),
                window_seconds=_env_float(
                    LOGIN_WINDOW_SECONDS_ENV_VAR, DEFAULT_LOGIN_WINDOW_SECONDS
                ),
            )
        return _login_rate_limiter


def reset_auth_limits() -> None:
    """Drop the process-wide instances (they are re-created on next use)."""

    global _password_work_limiter, _login_rate_limiter

    with _instances_lock:
        _password_work_limiter = None
        _login_rate_limiter = None
