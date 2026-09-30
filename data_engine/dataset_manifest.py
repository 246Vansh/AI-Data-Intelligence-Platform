"""
Dataset manifest: small JSON sidecar recording a dataset's identity
(dataset_id, owner_id, name, created_at, storage) next to its storage
artifact, so that identity survives a process restart even though
DatasetRegistry itself is in-memory only.

`storage` is a StorageReference ({"type": ..., "location": ...}), not a
Parquet-specific field. Manifests written before Step 58 carried a bare
"parquet_path" instead; read_manifest() still accepts those and reads
them as storage type "parquet" at that location.

Deliberately minimal: no schema, no row counts - those are re-derived
live from the Parquet file via DuckDBStorage.from_parquet whenever
needed, so the manifest can never drift out of sync with the data.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime

from data_engine.storage.reference import StorageReference, StorageReferenceError


class LegacyManifestError(ValueError):
    """
    Raised by read_manifest() for a manifest written before dataset
    ownership existed (no "owner_id" field).

    A distinct ValueError subclass so startup recovery can report it
    explicitly rather than as generic corruption - and so no caller is
    ever tempted to guess an owner for it. Such a dataset is left
    untouched on disk and simply not registered until its ownership is
    assigned deliberately.
    """


@dataclass
class DatasetManifest:
    dataset_id: str
    owner_id: str
    name: str | None
    created_at: datetime
    storage: StorageReference


def manifest_path_for(dataset_id: str, storage_root: str) -> str:
    """Path of dataset_id's manifest sidecar under storage_root."""
    return os.path.join(storage_root, f"{dataset_id}.json")


def manifest_path_for_artifact(artifact_path: str) -> str:
    """
    Derive a manifest's path from its sibling on-disk artifact's path
    (e.g. {dataset_id}.parquet -> {dataset_id}.json).
    """
    root, _ext = os.path.splitext(artifact_path)
    return f"{root}.json"


def write_manifest(
    dataset_id: str,
    name: str | None,
    created_at: datetime,
    storage: StorageReference,
    storage_root: str,
    owner_id: str,
) -> str:
    """
    Write dataset_id's manifest. Returns the path written.

    Raises ValueError for a missing owner_id - a persisted dataset must
    always record who owns it. Raises on any I/O failure - the caller
    (DatasetManager) is responsible for rollback.
    """
    if not isinstance(owner_id, str) or not owner_id:
        raise ValueError("Cannot write a dataset manifest without an owner_id.")

    os.makedirs(storage_root, exist_ok=True)
    path = manifest_path_for(dataset_id, storage_root)

    payload = {
        "dataset_id": dataset_id,
        "owner_id": owner_id,
        "name": name,
        "created_at": created_at.isoformat(),
        "storage": storage.to_dict(),
    }

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    return path


def read_manifest(path: str) -> DatasetManifest:
    """
    Parse and validate a manifest file.

    Raises ValueError for invalid JSON or a missing/malformed required
    field - callers (startup recovery) treat this as "skip", never as
    fatal. A manifest with no "owner_id" at all raises the more
    specific LegacyManifestError; no owner is ever invented for it.
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
    except KeyError as exc:
        raise ValueError(f"Manifest missing required field {exc}: {path}") from exc

    if not isinstance(dataset_id, str) or not dataset_id:
        raise ValueError(f"Manifest has invalid dataset_id: {path}")

    storage = _read_storage_reference(payload, path)

    try:
        created_at = datetime.fromisoformat(created_at_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Manifest has invalid created_at: {path}") from exc

    if "owner_id" not in payload:
        raise LegacyManifestError(f"Legacy manifest has no owner_id: {path}")

    owner_id = payload["owner_id"]
    if not isinstance(owner_id, str) or not owner_id:
        raise ValueError(f"Manifest has invalid owner_id: {path}")

    name = payload.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError(f"Manifest has invalid name: {path}")

    return DatasetManifest(
        dataset_id=dataset_id,
        owner_id=owner_id,
        name=name,
        created_at=created_at,
        storage=storage,
    )


def _read_storage_reference(payload: dict, path: str) -> StorageReference:
    """
    Resolve a manifest's storage reference, accepting both formats:
      - current: "storage": {"type": ..., "location": ...}
      - legacy (pre-Step 58): "parquet_path": "..." -> type "parquet"

    A manifest carrying both is rejected as ambiguous rather than
    silently preferring one - no writer ever produces both.
    """
    has_storage = "storage" in payload
    has_legacy = "parquet_path" in payload

    if has_storage and has_legacy:
        raise ValueError(f"Manifest has both storage and parquet_path: {path}")

    try:
        if has_storage:
            return StorageReference.from_dict(payload["storage"])

        if has_legacy:
            return StorageReference.parquet(payload["parquet_path"])

    except StorageReferenceError as exc:
        raise ValueError(f"Manifest has invalid storage reference ({exc}): {path}") from exc

    raise ValueError(f"Manifest missing required field 'storage': {path}")


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
