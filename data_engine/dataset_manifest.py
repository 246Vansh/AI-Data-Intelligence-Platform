"""
Dataset manifest: small JSON sidecar recording a dataset's identity
(dataset_id, name, created_at, parquet_path) next to its Parquet
artifact, so that identity survives a process restart even though
DatasetRegistry itself is in-memory only.

Deliberately minimal: no schema, no row counts - those are re-derived
live from the Parquet file via DuckDBStorage.from_parquet whenever
needed, so the manifest can never drift out of sync with the data.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime


@dataclass
class DatasetManifest:
    dataset_id: str
    name: str | None
    created_at: datetime
    parquet_path: str


def manifest_path_for(dataset_id: str, storage_root: str) -> str:
    """Path of dataset_id's manifest sidecar under storage_root."""
    return os.path.join(storage_root, f"{dataset_id}.json")


def manifest_path_for_parquet(parquet_path: str) -> str:
    """Derive a manifest's path from its sibling Parquet artifact's path."""
    root, _ext = os.path.splitext(parquet_path)
    return f"{root}.json"


def write_manifest(
    dataset_id: str,
    name: str | None,
    created_at: datetime,
    parquet_path: str,
    storage_root: str,
) -> str:
    """
    Write dataset_id's manifest. Returns the path written.

    Raises on any I/O failure - the caller (DatasetManager) is
    responsible for rollback.
    """
    os.makedirs(storage_root, exist_ok=True)
    path = manifest_path_for(dataset_id, storage_root)

    payload = {
        "dataset_id": dataset_id,
        "name": name,
        "created_at": created_at.isoformat(),
        "parquet_path": parquet_path,
    }

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    return path


def read_manifest(path: str) -> DatasetManifest:
    """
    Parse and validate a manifest file.

    Raises ValueError for invalid JSON or a missing/malformed required
    field - callers (startup recovery) treat this as "skip", never as
    fatal.
    """
    with open(path, "r", encoding="utf-8") as fh:
        try:
            payload = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid manifest JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"Manifest is not a JSON object: {path}")

    try:
        dataset_id = payload["dataset_id"]
        created_at_raw = payload["created_at"]
        parquet_path = payload["parquet_path"]
    except KeyError as exc:
        raise ValueError(f"Manifest missing required field {exc}: {path}") from exc

    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError(f"Manifest has invalid dataset_id: {path}")

    if not isinstance(parquet_path, str) or not parquet_path:
        raise ValueError(f"Manifest has invalid parquet_path: {path}")

    try:
        created_at = datetime.fromisoformat(created_at_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Manifest has invalid created_at: {path}") from exc

    name = payload.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError(f"Manifest has invalid name: {path}")

    return DatasetManifest(
        dataset_id=dataset_id,
        name=name,
        created_at=created_at,
        parquet_path=parquet_path,
    )


def delete_manifest(path: str) -> None:
    """
    Remove a manifest file if present. Raises OSError on failure - the
    caller (DatasetRegistry.delete) is responsible for catching/logging.
    """
    if os.path.exists(path):
        os.remove(path)


def find_manifest_paths(storage_root: str) -> list[str]:
    """
    List every manifest (*.json) path under storage_root, for startup
    recovery to scan. Empty list if storage_root doesn't exist yet.
    """
    if not os.path.isdir(storage_root):
        return []

    return sorted(
        os.path.join(storage_root, name)
        for name in os.listdir(storage_root)
        if name.endswith(".json")
    )
