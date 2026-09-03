from __future__ import annotations

from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset
from data_engine.execution.base import ExecutionEngine
from data_engine.execution.result import ExecutionResult
from data_engine.plan_executor import execute_plan


class PandasExecutionEngine(ExecutionEngine):
    """
    Minimal adapter exposing the existing Pandas execution path
    (plan_executor.execute_plan / query_engine.analyze) through the
    abstract ExecutionEngine contract.

    This class adds no filtering, grouping, aggregation, or sorting
    logic of its own - it owns none of that behavior. It only pulls a
    DataFrame out of the dataset through the storage contract and hands
    it to the untouched, already-tested pandas execution path. Callers
    that only know ExecutionEngine never learn that Pandas is involved.
    """

    def execute(
        self,
        dataset_reference: Dataset,
        validated_plan: AnalysisPlan,
    ) -> ExecutionResult:
        # Strictly through the storage contract - never
        # dataset_reference.dataframe, and never an isinstance check on
        # the concrete storage backend.
        dataframe = dataset_reference.storage.to_dataframe()

        result = execute_plan(dataframe, validated_plan)

        # Single conversion point, at the same place a DataFrame was
        # already being produced - no additional materialization, no
        # extra query. Truncation is not tracked by execute_plan()/
        # analyze() today (the head(effective_limit) call doesn't reveal
        # whether more rows existed), so it is never claimed as True here.
        return ExecutionResult(
            columns=result.columns.tolist(),
            rows=result.to_dict(orient="records"),
            row_count=len(result),
            truncated=False,
        )
