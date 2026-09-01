from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from data_engine.dataset import Dataset


class QualityEngine(ABC):
    """
    Abstract execution boundary for dataset quality analysis:
    duplicate-row detection, per-column missing-value tallies,
    constant-column detection, high-cardinality detection, and
    IQR-based numeric outlier counts.

    Mirrors data_engine.profiling.ProfilingEngine's shape: callers
    depend on this contract only, and must never know - and this
    contract itself must never reveal - whether a concrete engine
    computes it by pulling a full DataFrame into pandas or by running
    bounded aggregate SQL directly against DuckDB. No SQL, DataFrame,
    or other engine-specific detail belongs here.

    check_quality() receives a Dataset reference, never raw data of
    its own - a concrete engine may only read dataset contents through
    the Dataset/DatasetStorage abstraction, never by reaching past it.
    It does not materialize or own the dataset itself.
    """

    @abstractmethod
    def check_quality(self, dataset: Dataset) -> dict[str, Any]:
        """
        Compute {status, issue_count, issues} for a dataset - matching
        data_engine.data_quality.check_data_quality()'s response shape
        exactly.
        """
        raise NotImplementedError
