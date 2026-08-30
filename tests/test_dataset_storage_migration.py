"""Step 3 verification: Dataset is storage-agnostic (no DataFrame field).

These tests pin down that:
  - Dataset can only be constructed via `storage=` (PandasStorage today).
  - Dataset itself carries no pandas import / no `dataframe` field.
  - row_count/column_count/column_names are read strictly through the
    DatasetStorage abstraction.
  - Materializing a DataFrame requires going through
    `dataset.storage.to_dataframe()` - there is no `Dataset.dataframe`
    compatibility property.
  - DatasetRegistry registers/retrieves/deletes Dataset objects without
    ever touching or owning a DataFrame itself.
"""

import ast
import dataclasses
import inspect

import pandas as pd
import pytest

import data_engine.dataset as dataset_module
from data_engine.dataset import Dataset
from data_engine.dataset_registry import DatasetNotFoundError, DatasetRegistry
from data_engine.storage import DatasetStorage, PandasStorage


def _make_dataframe() -> pd.DataFrame:
    return pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"]})


def test_dataset_creates_with_pandas_storage():
    dataset = Dataset(storage=PandasStorage(_make_dataframe()), name="orders.csv")

    assert isinstance(dataset.storage, DatasetStorage)
    assert isinstance(dataset.storage, PandasStorage)
    assert dataset.name == "orders.csv"
    assert isinstance(dataset.dataset_id, str) and dataset.dataset_id


def test_dataset_module_has_no_pandas_import():
    # Source-level check: data_engine/dataset.py must not import pandas
    # at all, so Dataset stays completely storage-agnostic.
    source = inspect.getsource(dataset_module)
    tree = ast.parse(source)

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module.split(".")[0])

    assert "pandas" not in imported_names
    assert not hasattr(dataset_module, "pd")


def test_dataset_has_no_dataframe_field_or_attribute():
    field_names = {f.name for f in dataclasses.fields(Dataset)}
    assert "dataframe" not in field_names

    dataset = Dataset(storage=PandasStorage(_make_dataframe()))
    assert not hasattr(dataset, "dataframe")

    with pytest.raises(TypeError):
        Dataset(dataframe=_make_dataframe())  # old-style construction is gone


def test_dataset_reports_counts_and_names_via_storage():
    df = _make_dataframe()
    dataset = Dataset(storage=PandasStorage(df))

    assert dataset.row_count == 3
    assert dataset.column_count == 2
    assert dataset.column_names == ["id", "name"]


def test_dataset_materializes_dataframe_only_through_storage():
    df = _make_dataframe()
    dataset = Dataset(storage=PandasStorage(df))

    materialized = dataset.storage.to_dataframe()
    assert isinstance(materialized, pd.DataFrame)
    pd.testing.assert_frame_equal(materialized, df)


def test_registry_registers_and_deletes_dataset_without_owning_dataframe():
    registry = DatasetRegistry()
    dataset = Dataset(storage=PandasStorage(_make_dataframe()), name="events.csv")

    dataset_id = registry.register(dataset)
    assert dataset_id == dataset.dataset_id
    assert registry.exists(dataset_id)

    fetched = registry.get(dataset_id)
    assert fetched is dataset
    # The registry only ever hands back the Dataset/storage - never a
    # bare DataFrame of its own.
    assert fetched.storage.row_count() == 3

    registry.delete(dataset_id)
    assert not registry.exists(dataset_id)

    with pytest.raises(DatasetNotFoundError):
        registry.get(dataset_id)
