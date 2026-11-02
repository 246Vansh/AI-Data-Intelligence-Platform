import logging
import sqlite3
import threading
from dataclasses import dataclass

from fastapi import HTTPException, Request

from backend.auth import config as _auth_config
from backend.auth.config import AuthSettings, load_auth_settings
from backend.auth.sessions import SessionService
from data_engine.dataset import Dataset
from data_engine.dataset_manager import dataset_manager
from data_engine.dataset_registry import DatasetNotFoundError, DatasetRegistry


logger = logging.getLogger(__name__)


def get_current_dataset():
    """
    Return the dataset currently loaded by the application.
    """

    return dataset_manager.get_dataframe()


def get_current_dataset_name():
    """
    Return the filename of the currently loaded dataset.
    """

    return dataset_manager.get_filename()


def has_dataset_loaded():
    """
    Check whether a dataset is currently available.
    """

    return dataset_manager.is_loaded()


# =========================================================
# AUTHENTICATION
#
# Deliberately small, replaceable boundary. Routes depend only on
# get_current_user() and the AuthenticatedUser it returns - swapping
# in a real identity provider later means replacing this one function
# (or overriding it via app.dependency_overrides), not touching routes.
#
# Auth Step 3: identity comes ONLY from the HttpOnly session cookie,
# validated server-side by backend.auth.sessions.SessionService. No
# user id is ever taken from a body, query parameter or header. The
# development identity (DEV_USER_ID) applies only when AUTH_DEV_MODE is
# explicitly enabled - see backend.auth.config for the guard that keeps
# it out of production.
# =========================================================


# Re-exported for existing importers (tests, tooling).
DEV_USER_ID_ENV_VAR = _auth_config.DEV_USER_ID_ENV_VAR
DEFAULT_DEV_USER_ID = _auth_config.DEFAULT_DEV_USER_ID

_NOT_AUTHENTICATED_DETAIL = "Not authenticated."

_dev_mode_warned = threading.Event()

# One SessionService per (db path, timeouts): constructing one runs
# idempotent schema setup, which shouldn't happen on every request.
_session_services: dict[tuple, SessionService] = {}
_session_services_lock = threading.Lock()


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str


def get_session_service(settings: AuthSettings) -> SessionService:
    key = (settings.db_path, settings.idle_timeout, settings.absolute_lifetime)

    with _session_services_lock:
        service = _session_services.get(key)
        if service is None:
            service = SessionService(
                settings.db_path,
                idle_timeout=settings.idle_timeout,
                absolute_lifetime=settings.absolute_lifetime,
            )
            _session_services[key] = service
        return service


def _not_authenticated() -> HTTPException:
    # One response for missing, malformed, unknown, expired and revoked
    # sessions alike, so a caller learns nothing about which it was.
    return HTTPException(status_code=401, detail=_NOT_AUTHENTICATED_DETAIL)


def get_current_user(request: Request = None) -> AuthenticatedUser:
    """
    Resolve the identity of the caller making the current request.

    FastAPI injects `request`. Settings are read per call, so env
    changes apply without re-importing the application.

    - AUTH_DEV_MODE (explicit, and only with Secure cookies off):
      the DEV_USER_ID development identity, with a one-time warning.
    - Otherwise: the session cookie must name a live session; its
      user's UUID is returned. Anything else is a 401.
    """

    settings = load_auth_settings()

    if settings.dev_mode:
        if not _dev_mode_warned.is_set():
            _dev_mode_warned.set()
            logger.warning(
                "AUTH_DEV_MODE is active: authentication is BYPASSED and every "
                "request is treated as development user %r. Never enable this "
                "outside local development or tests.",
                settings.dev_user_id,
            )
        return AuthenticatedUser(user_id=settings.dev_user_id)

    if request is None:
        raise _not_authenticated()

    token = request.cookies.get(settings.cookie_name)
    if not token:
        raise _not_authenticated()

    try:
        service = get_session_service(settings)
    except (sqlite3.Error, OSError) as exc:
        logger.error("Authentication store unavailable: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503, detail="Authentication is temporarily unavailable."
        ) from None

    # Fails closed: SessionService returns None on any database error.
    session = service.validate_session(token)
    if session is None:
        raise _not_authenticated()

    return AuthenticatedUser(user_id=session.user_id)


# =========================================================
# AUTHORIZATION
# =========================================================


def dataset_not_found(dataset_id: str) -> HTTPException:
    """
    The one 404 every dataset-scoped route returns for a dataset_id the
    caller can't use - missing, someone else's, or deleted mid-request
    (its storage closed underneath the request; see
    data_engine.storage.StorageClosedError). Built in one place so all
    of those cases stay byte-for-byte indistinguishable.
    """

    return HTTPException(
        status_code=404,
        detail=f"No dataset found for dataset_id: {dataset_id!r}",
    )


def authorize_dataset(
    registry: DatasetRegistry,
    dataset_id: str,
    user: AuthenticatedUser,
) -> Dataset:
    """
    Resolve dataset_id through `registry` and return it only if `user`
    owns it.

    The single ownership check shared by every dataset-scoped route.
    The registry is passed in rather than imported so it stays a plain,
    authorization-agnostic catalog, and so each route module keeps
    resolving through its own registry reference.

    A dataset that exists but belongs to someone else - or to no one -
    gets the exact same 404 as one that doesn't exist, so a caller can
    never probe for other users' dataset_ids.
    """

    not_found = dataset_not_found(dataset_id)

    try:
        dataset = registry.get(dataset_id)

    except DatasetNotFoundError as exc:
        raise not_found from exc

    if not dataset.owner_id or dataset.owner_id != user.user_id:
        raise not_found

    return dataset
