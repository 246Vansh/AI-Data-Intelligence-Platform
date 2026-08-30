from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from data_engine.dataset import Dataset


class ProfilingEngine(ABC):
    """
    Abstract execution boundary for basic dataset inspection
    statistics: row/column counts, per-column missing-value tallies,
    distinct-value counts, min/max bounds, and basic data types.

    Mirrors data_engine.execution.ExecutionEngine's shape: callers
    depend on this contract only, and must never know - and this
    contract itself must never reveal - whether a concrete engine
    computes these statistics by pulling a full DataFrame into pandas
    or by running bounded aggregate SQL directly against DuckDB. No
    SQL, DataFrame, or other engine-specific detail belongs here.

    basic_statistics() receives a Dataset reference, never raw data of
    its own - a concrete engine may only read dataset contents through
    the Dataset/DatasetStorage abstraction, never by reaching past it.
    It does not materialize or own the dataset itself.
    """

    @abstractmethod
    def basic_statistics(self, dataset: Dataset) -> dict[str, Any]:
        """
        Compute row_count, column_count, duplicate_rows,
        memory_usage_bytes, and per-column {data_type, missing_count,
        missing_percentage, distinct_count, min, max} statistics for a
        dataset.

        duplicate_rows and memory_usage_bytes are bridged in for
        callers reshaping this into the historical
        data_engine.profiler.profile_dataset() response shape - they
        are not otherwise part of this contract's "basic statistics".
        memory_usage_bytes is None for engines with no faithful native
        equivalent to pandas' memory_usage(deep=True) (e.g. DuckDB).
        """
        raise NotImplementedError
