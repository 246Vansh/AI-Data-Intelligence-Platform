from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from data_engine.dataset import Dataset


class MetadataEngine(ABC):
    """
    Abstract execution boundary for dataset metadata generation:
    per-column data type, semantic role (time/metric/dimension),
    allowed operations, nullability, missing/unique counts, and a
    bounded sample of non-null values - plus the dataset-level
    time_column/time_columns summary derived from those per-column
    roles.

    Mirrors data_engine.profiling.ProfilingEngine's shape: callers
    depend on this contract only, and must never know - and this
    contract itself must never reveal - whether a concrete engine
    computes it by pulling a full DataFrame into pandas or by running
    bounded SQL directly against DuckDB. No SQL, DataFrame, or other
    engine-specific detail belongs here.

    get_metadata() receives a Dataset reference, never raw data of its
    own - a concrete engine may only read dataset contents through the
    Dataset/DatasetStorage abstraction, never by reaching past it. It
    does not materialize or own the dataset itself.
    """

    @abstractmethod
    def get_metadata(self, dataset: Dataset) -> dict[str, Any]:
        """
        Compute row_count, column_count, per-column {data_type, role,
        allowed_operations, nullable, missing_count, unique_values,
        sample_values}, plus time_column/time_columns, for a dataset -
        matching data_engine.metadata.get_metadata()'s response shape
        exactly.
        """
        raise NotImplementedError
