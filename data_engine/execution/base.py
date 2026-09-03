from __future__ import annotations

from abc import ABC, abstractmethod

from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset
from data_engine.execution.result import ExecutionResult


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

    The return type is ExecutionResult - an engine-neutral result
    representation (columns/rows/row_count/truncated). No concrete
    engine may return a raw pandas DataFrame (or any other
    backend-specific object) from execute(); each engine converts its
    own internal result into an ExecutionResult exactly once, at the
    end of execute().
    """

    @abstractmethod
    def execute(
        self,
        dataset_reference: Dataset,
        validated_plan: AnalysisPlan,
    ) -> ExecutionResult:
        """
        Execute a validated AnalysisPlan against a dataset and return
        the analytical result.
        """
        raise NotImplementedError
