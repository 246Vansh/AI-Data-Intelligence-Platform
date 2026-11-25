"""
R4: per-operation query deadlines.

A deadline is attached to the *current thread's context* (a
ContextVar) by whoever runs a unit of bounded work - in production the
analysis JobManager wraps every task it runs on its pool in
``query_deadline(...)``. Storage backends that can stop a running query
(DuckDBStorage, via ``connection.interrupt()``) consult it:

  - before starting a query: an already-expired deadline raises
    QueryTimeoutError without running anything;
  - while a query runs: a timer interrupts that one query when the
    deadline passes, and the storage raises QueryTimeoutError only once
    the interrupt has actually stopped the query.

Without an active deadline (scripts, tests, startup recovery) nothing
changes: queries run unbounded exactly as before.

The data_engine layer stays framework-free: translating
QueryTimeoutError into an HTTP status is the API layer's job.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_deadline: ContextVar[float | None] = ContextVar("query_deadline", default=None)


class QueryTimeoutError(RuntimeError):
    """
    The current operation's deadline expired. Raised only when the
    query was confirmed stopped (the backend reported the interrupt) or
    was never started because the deadline had already passed.
    """


@contextmanager
def query_deadline(seconds: float | None) -> Iterator[None]:
    """
    Bound every interruptible query run inside this block to finish
    within ``seconds`` from now. ``None`` adds no bound. Nested blocks
    never extend an outer deadline - the earlier one always wins.
    """

    if seconds is None:
        yield
        return

    new_deadline = time.monotonic() + max(0.0, float(seconds))
    outer = _deadline.get()

    if outer is not None:
        new_deadline = min(new_deadline, outer)

    token = _deadline.set(new_deadline)

    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_seconds() -> float | None:
    """Seconds left on the active deadline (may be <= 0), or None."""

    deadline = _deadline.get()

    if deadline is None:
        return None

    return deadline - time.monotonic()


def check_deadline() -> None:
    """Raise QueryTimeoutError if the active deadline has passed."""

    remaining = remaining_seconds()

    if remaining is not None and remaining <= 0:
        raise QueryTimeoutError("The operation exceeded its time limit.")
