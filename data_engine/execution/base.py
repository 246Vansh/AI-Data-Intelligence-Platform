from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset


class ExecutionEngine(ABC):
    """
    Abstract execution boundary: Dataset/Storage -> ExecutionEngine ->
    analytical result.

    Callers depend on this contract only. They must not know - and this
    contract itself must never reveal - whether a concrete engine runs
    on Pandas, DuckDB, or anything else. No SQL, DataFrame, or other
    engine-specific detail belongs here.

    execute() is the single operation the contract exposes. It:
      - receives a Dataset reference, never raw data of its own. A
        concrete engine may only read dataset contents through the
        Dataset/DatasetStorage abstraction (e.g. storage.to_dataframe()),
        never by reaching past it or branching on its concrete type.
      - receives an already-validated, canonical AnalysisPlan. Plan
        validation is owned upstream (plan_validator) - an
        ExecutionEngine never validates or re-interprets plan semantics.
      - does not materialize or own the dataset itself; it delegates to
        whatever access pattern the underlying storage/engine supports.

    The return type is intentionally left as the existing analytical
    result representation used downstream (e.g. a DataFrame today) -
    this boundary is about decoupling *how* a plan is executed, not
    about redesigning *what* a result looks like.
    """

    @abstractmethod
    def execute(
        self,
        dataset_reference: Dataset,
        validated_plan: AnalysisPlan,
    ) -> Any:
        """
        Execute a validated AnalysisPlan against a dataset and return
        the analytical result.
        """
        raise NotImplementedError
