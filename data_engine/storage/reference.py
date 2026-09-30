"""
Storage reference: a small, persistable description of *where* and *how*
a dataset's data is stored - a backend type plus a location - so that
DatasetManifest and startup recovery no longer assume every dataset is
a local Parquet file named by a `parquet_path` field.

Deliberately minimal: a frozen dataclass, JSON (de)serialization, and
one dispatch table (_OPENERS) mapping a storage type to the function
that opens it as a DatasetStorage. Adding a future storage type means
adding one entry to that table - no type checks elsewhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from data_engine.storage.base import DatasetStorage
from data_engine.storage.duckdb_storage import DuckDBStorage


PARQUET_STORAGE_TYPE = "parquet"


class StorageReferenceError(ValueError):
    """
    A storage reference is malformed (wrong shape, missing or empty
    type/location). A ValueError subclass so manifest readers and
    startup recovery treat it exactly like any other invalid manifest.
    """


class UnsupportedStorageTypeError(StorageReferenceError):
    """A well-formed storage reference names a type no opener exists for."""

    def __init__(self, storage_type: str):
        self.storage_type = storage_type
        super().__init__(f"Unsupported storage type: {storage_type!r}")


@dataclass(frozen=True)
class StorageReference:
    type: str
    location: str

    def __post_init__(self) -> None:
        if not isinstance(self.type, str) or not self.type:
            raise StorageReferenceError("Storage reference has invalid type.")

        if not isinstance(self.location, str) or not self.location:
            raise StorageReferenceError("Storage reference has invalid location.")

    @classmethod
    def parquet(cls, location: str) -> "StorageReference":
        return cls(type=PARQUET_STORAGE_TYPE, location=location)

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "location": self.location}

    @classmethod
    def from_dict(cls, payload: Any) -> "StorageReference":
        """
        Parse a persisted {"type": ..., "location": ...} object.

        Raises StorageReferenceError for anything malformed. Does NOT
        check that the type is supported - that is open_storage()'s
        job, so parsing stays independent of which backends exist.
        """
        if not isinstance(payload, dict):
            raise StorageReferenceError("Storage reference is not a JSON object.")

        try:
            return cls(type=payload["type"], location=payload["location"])
        except KeyError as exc:
            raise StorageReferenceError(
                f"Storage reference missing required field {exc}."
            ) from exc


def _open_parquet(location: str) -> DatasetStorage:
    # Explicit existence check so a missing file is reported as such,
    # rather than as whatever DuckDB happens to raise for it.
    if not os.path.exists(location):
        raise FileNotFoundError(f"Parquet file missing at {location!r}.")

    return DuckDBStorage.from_parquet(location)


_OPENERS: dict[str, Callable[[str], DatasetStorage]] = {
    PARQUET_STORAGE_TYPE: _open_parquet,
}


def open_storage(reference: StorageReference) -> DatasetStorage:
    """
    Open the DatasetStorage a reference points at. The single dispatch
    point on storage type for persisted datasets.

    Raises UnsupportedStorageTypeError for an unknown type, and lets
    the opener's own errors (missing file, unreadable Parquet)
    propagate - callers such as startup recovery catch and skip.
    """
    opener = _OPENERS.get(reference.type)

    if opener is None:
        raise UnsupportedStorageTypeError(reference.type)

    return opener(reference.location)
