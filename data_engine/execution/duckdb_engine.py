from __future__ import annotations

import pandas as pd

from data_engine.analysis_plan import AnalysisPlan
from data_engine.dataset import Dataset
from data_engine.duckdb_query_engine import execute_plan_duckdb
from data_engine.execution.base import ExecutionEngine


class DuckDBExecutionEngine(ExecutionEngine):
    """
    DuckDB-native adapter exposing the existing execute_plan_duckdb()
    SQL execution path (filtering, time bucketing, grouping,
    aggregation, sorting, limiting - all run as SQL by DuckDB itself)
    through the abstract ExecutionEngine contract.

    This class adds no query logic of its own: it forwards straight to
    data_engine/duckdb_query_engine.py, which already performs every
    analytical operation natively inside DuckDB. execute() never calls
    dataset_reference.storage.to_dataframe() and never materializes the
    full dataset into pandas - only the already filtered/aggregated/
    sorted/limited *result* is a DataFrame, produced once at the very
    end by execute_plan_duckdb() itself (the same compatibility-
    boundary pattern DatasetStorage.to_dataframe() uses elsewhere).
    """

    def execute(
        self,
        dataset_reference: Dataset,
        validated_plan: AnalysisPlan,
    ) -> pd.DataFrame:
        # Pass the storage object straight through to the DuckDB-native
        # query engine. No to_dataframe() call, no full-dataset
        # materialization - execute_plan_duckdb() runs SQL directly
        # against dataset_reference.storage.connection/table_name.
        return execute_plan_duckdb(dataset_reference.storage, validated_plan)
