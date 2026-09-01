"""Step 3: Dataset lifecycle, resource cleanup & deletion.

Automated coverage for the 10 lifecycle requirements exercised
manually by the ad-hoc verification script during Step 3
implementation:

  R1.  DatasetRegistry.delete() removes the dataset - exists()
       becomes False and get() raises DatasetNotFoundError.
       (Already covered by
       test_dataset_storage_migration.py::
       test_registry_registers_and_deletes_dataset_without_owning_dataframe
       - not duplicated here.)
  R2.  DatasetManager's active pointer is cleared when the deleted
       dataset was the active one.
  R3.  DatasetManager's active pointer is left untouched when the
       deleted dataset was NOT the active one.
  R4.  DuckDBStorage.close() explicitly closes the connection - a
       read attempted afterward raises instead of touching a closed
       connection.
  R5.  DuckDBStorage.close() is idempotent - calling it a second time
       does not raise.
  R6.  DatasetRegistry.delete() deletes the on-disk Parquet artifact
       for a from_parquet()-backed DuckDBStorage.
  R7.  PandasStorage.close() is a safe no-op: it does not raise, and
       its artifact_path is None (nothing on disk to clean up).
  R8.  Dataset.cache becomes unreachable after deletion: once a
       dataset is deleted, the registry can no longer hand back the
       Dataset object (and therefore its .cache) by id.
  R9.  DatasetRegistry.delete() on an unknown dataset_id raises
       DatasetNotFoundError rather than silently succeeding.
  R10. Failure isolation: a storage.close() failure during delete()
       is logged, does not roll back the registry removal, and does
       not propagate out of delete() (no 500 at the route layer).

Only DatasetRegistry/DatasetManager/DatasetStorage are exercised
directly - no HTTP layer, no AI/planner components, matching the
Step 3 scope boundary.
"""

from __future__ import annotations

import logging
import os

import pandas as pd
import pytest

from data_engine.dataset import Dataset
from data_engine.dataset_manager import DatasetManager
from data_engine.dataset_registry import DatasetNotFoundError, DatasetRegistry
from data_engine.storage import DatasetStorage, DuckDBStorage, PandasStorage


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})


class _RaisingCloseStorage(DatasetStorage):
    """
    Test-only DatasetStorage stub whose close() always raises, so
    delete()'s failure-isolation behavior (R10) can be exercised
    without depending on a real backend actually failing to close.
    """

    def __init__(self, dataframe: pd.DataFrame):
        self._dataframe = dataframe

    def to_dataframe(self) -> pd.DataFrame:
        return self._dataframe

    def row_count(self) -> int:
        return len(self._dataframe)

    def column_count(self) -> int:
        return len(self._dataframe.columns)

    def column_names(self) -> list[str]:
        return self._dataframe.columns.tolist()

    def close(self) -> None:
        raise RuntimeError("simulated close() failure")


# =========================================================
# R2 / R3 - DatasetManager active-pointer integration
# =========================================================


def test_delete_of_active_dataset_clears_active_pointer():
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    dataset = manager.register_csv_bytes(
        b"a,b\n1,x\n2,y\n",
        filename="active.csv",
    )

    assert manager.is_loaded()

    registry.delete(dataset.dataset_id)
    manager.clear_dataset(dataset.dataset_id)

    assert manager._active_id is None
    assert not manager.is_loaded()


def test_delete_of_inactive_dataset_leaves_active_pointer_untouched():
    registry = DatasetRegistry()
    manager = DatasetManager(registry=registry)

    inactive = Dataset(storage=PandasStorage(_make_dataframe()), name="inactive.csv")
    registry.register(inactive)

    active = manager.register_csv_bytes(
        b"a,b\n1,x\n2,y\n",
        filename="active.csv",
    )

    registry.delete(inactive.dataset_id)
    manager.clear_dataset(inactive.dataset_id)

    assert manager._active_id == active.dataset_id
    assert manager.is_loaded()


# =========================================================
# R4 / R5 - DuckDBStorage.close() semantics
# =========================================================


def test_duckdb_storage_close_blocks_further_reads():
    storage = DuckDBStorage(_make_dataframe())

    assert storage.row_count() == 3  # works before close

    storage.close()

    with pytest.raises(RuntimeError):
        storage.row_count()

    with pytest.raises(RuntimeError):
        storage.to_dataframe()


def test_duckdb_storage_close_is_idempotent():
    storage = DuckDBStorage(_make_dataframe())

    storage.close()
    storage.close()  # must not raise


# =========================================================
# R6 - Parquet artifact cleanup
# =========================================================


def test_registry_delete_removes_parquet_artifact_from_disk(tmp_path):
    registry = DatasetRegistry()

    df = _make_dataframe()
    parquet_path = tmp_path / "dataset.parquet"
    df.to_parquet(parquet_path)

    storage = DuckDBStorage.from_parquet(str(parquet_path))
    dataset = Dataset(storage=storage, name="dataset.csv")
    registry.register(dataset)

    assert os.path.exists(parquet_path)

    registry.delete(dataset.dataset_id)

    assert not os.path.exists(parquet_path)


# =========================================================
# R7 - PandasStorage.close() no-op
# =========================================================


def test_pandas_storage_close_is_a_safe_noop():
    storage = PandasStorage(_make_dataframe())

    assert storage.artifact_path is None

    storage.close()  # must not raise
    storage.close()  # calling twice must not raise either


# =========================================================
# R8 - Dataset.cache unreachable after deletion
# =========================================================


def test_dataset_cache_unreachable_after_delete():
    registry = DatasetRegistry()
    dataset = Dataset(storage=PandasStorage(_make_dataframe()), name="cached.csv")
    dataset.cache["profile"] = {"rows": 3}

    registry.register(dataset)
    registry.delete(dataset.dataset_id)

    with pytest.raises(DatasetNotFoundError):
        registry.get(dataset.dataset_id)

    # The only way any caller could reach dataset.cache again is
    # through the registry - and the registry no longer knows this
    # dataset_id at all.
    assert not registry.exists(dataset.dataset_id)
    assert all(d.dataset_id != dataset.dataset_id for d in registry.list())


# =========================================================
# R9 - delete() on an unknown dataset_id
# =========================================================


def test_delete_unknown_dataset_id_raises_not_found():
    registry = DatasetRegistry()

    with pytest.raises(DatasetNotFoundError):
        registry.delete("does-not-exist")


# =========================================================
# R10 - Failure isolation on storage.close()
# =========================================================


def test_delete_survives_storage_close_failure_and_stays_removed(caplog):
    registry = DatasetRegistry()
    dataset = Dataset(storage=_RaisingCloseStorage(_make_dataframe()), name="broken.csv")
    registry.register(dataset)

    with caplog.at_level(logging.WARNING, logger="data_engine.dataset_registry"):
        registry.delete(dataset.dataset_id)  # must not raise

    assert not registry.exists(dataset.dataset_id)

    with pytest.raises(DatasetNotFoundError):
        registry.get(dataset.dataset_id)

    assert "Failed to close storage" in caplog.text
