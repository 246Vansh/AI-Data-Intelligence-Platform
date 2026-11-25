"""
R4: shared, validated HTTP client settings for the AI planner providers.

Every analysis runs on the bounded analysis pool, so an AI request that
hangs holds a worker. Both providers previously parsed
AI_REQUEST_TIMEOUT_SECONDS with a bare float() (a typo crashed every AI
request) and left retries at the SDK default implicitly. These readers
make both explicit; the defaults keep the existing behaviour (60s per
attempt, the SDKs' default of 2 retries), so the worst case stays about
3 x 60s - below the analysis task deadline (backend.jobs).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0
DEFAULT_MAX_RETRIES = 2
_MAX_RETRIES_CEILING = 5


def read_request_timeout() -> float:
    raw = os.getenv("AI_REQUEST_TIMEOUT_SECONDS")

    if raw is None or raw.strip() == "":
        return DEFAULT_REQUEST_TIMEOUT_SECONDS

    try:
        value = float(raw)
    except ValueError:
        value = 0.0

    if not value > 0:
        logger.warning(
            "Ignoring invalid AI_REQUEST_TIMEOUT_SECONDS=%r; using %s.",
            raw,
            DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        return DEFAULT_REQUEST_TIMEOUT_SECONDS

    return value


def read_max_retries() -> int:
    raw = os.getenv("AI_MAX_RETRIES")

    if raw is None or raw.strip() == "":
        return DEFAULT_MAX_RETRIES

    try:
        value = int(raw)
    except ValueError:
        value = -1

    if not 0 <= value <= _MAX_RETRIES_CEILING:
        logger.warning(
            "Ignoring invalid AI_MAX_RETRIES=%r (must be 0-%d); using %d.",
            raw,
            _MAX_RETRIES_CEILING,
            DEFAULT_MAX_RETRIES,
        )
        return DEFAULT_MAX_RETRIES

    return value
