from __future__ import annotations

import pandas as pd

from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset
from data_engine.execution.base import ExecutionEngine
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
    ) -> pd.DataFrame:
        # Strictly through the storage contract - never
        # dataset_reference.dataframe, and never an isinstance check on
        # the concrete storage backend.
        dataframe = dataset_reference.storage.to_dataframe()

        return execute_plan(dataframe, validated_plan)
