"""
Step 60A - minimal semantic layer.

build_semantic_dataset() reshapes existing dataset metadata into
dimensions / metrics / time_dimensions without reading data, renaming
columns, or altering any metadata value.
"""

from __future__ import annotations

import copy

import pytest

from data_engine.metadata import get_allowed_operations
from data_engine.semantic import (
    SemanticDataset,
    SemanticField,
    build_semantic_dataset,
)


def _column(role: str, data_type: str) -> dict:
    return {
        "data_type": data_type,
        "role": role,
        "allowed_operations": get_allowed_operations(role),
        "nullable": False,
        "missing_count": 0,
        "unique_values": 3,
        "sample_values": ["a", "b"],
    }


@pytest.fixture
def metadata() -> dict:
    return {
        "row_count": 10,
        "column_count": 5,
        "columns": {
            "Order Date": _column("time", "datetime"),
            "Region ": _column("dimension", "string"),
            "net_Revenue($)": _column("metric", "float"),
            "ship_year": _column("time", "integer"),
            "Qty": _column("metric", "integer"),
        },
        "time_column": "Order Date",
        "time_columns": ["Order Date", "ship_year"],
    }


def test_metric_columns_become_metrics(metadata):
    semantic = build_semantic_dataset(metadata)

    assert [field.column for field in semantic.metrics] == ["net_Revenue($)", "Qty"]
    assert all(field.role == "metric" for field in semantic.metrics)


def test_dimension_columns_become_dimensions(metadata):
    semantic = build_semantic_dataset(metadata)

    assert [field.column for field in semantic.dimensions] == ["Region "]


def test_time_columns_become_time_dimensions(metadata):
    semantic = build_semantic_dataset(metadata)

    assert [field.column for field in semantic.time_dimensions] == [
        "Order Date",
        "ship_year",
    ]
    # Time columns are not duplicated into dimensions or metrics.
    other = {field.column for field in semantic.dimensions + semantic.metrics}
    assert other.isdisjoint({"Order Date", "ship_year"})


def test_time_dimensions_sourced_only_from_time_columns(metadata):
    metadata["time_columns"] = ["ship_year"]

    semantic = build_semantic_dataset(metadata)

    assert [field.column for field in semantic.time_dimensions] == ["ship_year"]


def test_time_columns_without_column_entry_are_not_invented(metadata):
    metadata["time_columns"] = ["Order Date", "not_a_column"]

    semantic = build_semantic_dataset(metadata)

    assert [field.column for field in semantic.time_dimensions] == ["Order Date"]


def test_physical_column_names_preserved_exactly(metadata):
    semantic = build_semantic_dataset(metadata)
    fields = semantic.dimensions + semantic.metrics + semantic.time_dimensions

    assert {field.column for field in fields} == set(metadata["columns"])
    assert all(field.name == field.column for field in fields)


def test_metadata_values_preserved(metadata):
    semantic = build_semantic_dataset(metadata)

    for field in semantic.dimensions + semantic.metrics + semantic.time_dimensions:
        source = metadata["columns"][field.column]
        assert field.role == source["role"]
        assert field.data_type == source["data_type"]
        assert list(field.allowed_operations) == source["allowed_operations"]


@pytest.mark.parametrize(
    ("role", "expected"),
    [("metric", "sum"), ("dimension", "count"), ("time", None)],
)
def test_default_aggregation_rules(metadata, role, expected):
    semantic = build_semantic_dataset(metadata)
    fields = semantic.dimensions + semantic.metrics + semantic.time_dimensions
    matching = [field for field in fields if field.role == role]

    assert matching
    assert all(field.default_aggregation == expected for field in matching)


def test_primary_time_column_preserved(metadata):
    metadata["time_column"] = "ship_year"

    assert build_semantic_dataset(metadata).primary_time_column == "ship_year"


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"columns": {}},
        {"columns": None, "time_columns": None, "time_column": None},
        {"row_count": 0, "column_count": 0, "columns": {}, "time_column": None, "time_columns": []},
    ],
)
def test_empty_or_missing_sections_are_deterministic(value):
    semantic = build_semantic_dataset(value)

    assert semantic == SemanticDataset()
    assert semantic.dimensions == ()
    assert semantic.metrics == ()
    assert semantic.time_dimensions == ()
    assert semantic.primary_time_column is None


def test_columns_with_unknown_role_are_ignored():
    semantic = build_semantic_dataset(
        {"columns": {"x": {"role": "other", "data_type": "string"}}}
    )

    assert semantic == SemanticDataset()


def test_build_is_deterministic(metadata):
    assert build_semantic_dataset(metadata) == build_semantic_dataset(metadata)


def test_does_not_mutate_input(metadata):
    snapshot = copy.deepcopy(metadata)

    semantic = build_semantic_dataset(metadata)

    assert metadata == snapshot
    # Fields hold their own copy of allowed_operations, not the input list.
    field = semantic.metrics[0]
    assert isinstance(field, SemanticField)
    assert field.allowed_operations is not metadata["columns"][field.column]["allowed_operations"]
