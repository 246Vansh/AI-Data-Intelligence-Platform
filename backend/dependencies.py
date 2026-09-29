import os
from dataclasses import dataclass

from fastapi import HTTPException

from data_engine.dataset import Dataset
from data_engine.dataset_manager import dataset_manager
from data_engine.dataset_registry import DatasetNotFoundError, DatasetRegistry


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
# For now there is no real authentication: every request is the
# deterministic development identity named by DEV_USER_ID_ENV_VAR.
# =========================================================


DEV_USER_ID_ENV_VAR = "DEV_USER_ID"
DEFAULT_DEV_USER_ID = "dev-user"


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str


def get_current_user() -> AuthenticatedUser:
    """
    Resolve the identity of the caller making the current request.

    Read per call (not at import time) so the development identity can
    be changed without re-importing the application.
    """

    user_id = os.environ.get(DEV_USER_ID_ENV_VAR, "").strip()

    return AuthenticatedUser(user_id=user_id or DEFAULT_DEV_USER_ID)


# =========================================================
# AUTHORIZATION
# =========================================================


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

    not_found = HTTPException(
        status_code=404,
        detail=f"No dataset found for dataset_id: {dataset_id!r}",
    )

    try:
        dataset = registry.get(dataset_id)

    except DatasetNotFoundError as exc:
        raise not_found from exc

    if not dataset.owner_id or dataset.owner_id != user.user_id:
        raise not_found

    return dataset
