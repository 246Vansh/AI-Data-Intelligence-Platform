"""Regression tests for DuckDB time-bucketing date parsing.

DuckDB's TRY_CAST(... AS TIMESTAMP) only understands ISO-8601, so
slash-formatted strings such as '11/1/2022' used to become NULL and be
dropped, yielding 0 rows for e.g. "monthly revenue over time". These
tests pin the DuckDB path to the pandas path's parsing and bucketing
semantics for string-typed time columns.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data_engine.analysis_plan import AnalysisPlan
from data_engine.duckdb_query_engine import execute_plan_duckdb
from data_engine.plan_executor import execute_plan
from data_engine.storage import DuckDBStorage


def _time_plan(time_column: str, granularity: str) -> AnalysisPlan:
    return AnalysisPlan(
        group_by=[time_column],
        metric="amount",
        aggregation="sum",
        sort="asc",
        sort_by="time",
        time_granularity=granularity,
        time_column=time_column,
    )


def _slash_dataframe() -> pd.DataFrame:
    # Deliberately generic column name - nothing keys off "order_date".
    return pd.DataFrame(
        {
            "sold_on": [
                "11/1/2022",
                "11/15/2022",
                "12/3/2022",
                "1/5/2023",
                "not a date",
                "13/45/2022",
            ],
            "amount": [100.0, 50.0, 25.0, 10.0, 999.0, 999.0],
        }
    )


def _normalize(df: pd.DataFrame, time_column: str) -> pd.DataFrame:
    result = df.copy()
    result[time_column] = pd.to_datetime(result[time_column]).astype("datetime64[ns]")
    return result.reset_index(drop=True)


def test_slash_dates_are_parsed_into_monthly_buckets():
    result = execute_plan_duckdb(
        DuckDBStorage(_slash_dataframe()), _time_plan("sold_on", "month")
    )

    assert len(result) == 3
    assert list(pd.to_datetime(result["sold_on"])) == [
        pd.Timestamp("2022-11-01"),
        pd.Timestamp("2022-12-01"),
        pd.Timestamp("2023-01-01"),
    ]
    assert list(result["sum_amount"]) == [150.0, 25.0, 10.0]


def test_invalid_dates_are_still_excluded():
    result = execute_plan_duckdb(
        DuckDBStorage(_slash_dataframe()), _time_plan("sold_on", "month")
    )

    # The two unparseable rows each carry 999.0 - neither may leak in.
    assert result["sum_amount"].sum() == 185.0
    assert result["sold_on"].notna().all()


def test_iso_dates_continue_to_work():
    df = pd.DataFrame(
        {
            "sold_on": ["2022-11-01", "2022-11-20 08:30:00", "2023-02-14", "bogus"],
            "amount": [1.0, 2.0, 4.0, 8.0],
        }
    )

    result = execute_plan_duckdb(DuckDBStorage(df), _time_plan("sold_on", "month"))

    assert list(pd.to_datetime(result["sold_on"])) == [
        pd.Timestamp("2022-11-01"),
        pd.Timestamp("2023-02-01"),
    ]
    assert list(result["sum_amount"]) == [3.0, 4.0]


def test_native_timestamp_column_still_buckets():
    df = pd.DataFrame(
        {
            "sold_on": pd.to_datetime(["2022-11-01", "2022-11-20", "2023-02-14"]),
            "amount": [1.0, 2.0, 4.0],
        }
    )

    result = execute_plan_duckdb(DuckDBStorage(df), _time_plan("sold_on", "month"))

    assert list(pd.to_datetime(result["sold_on"])) == [
        pd.Timestamp("2022-11-01"),
        pd.Timestamp("2023-02-01"),
    ]
    assert list(result["sum_amount"]) == [3.0, 4.0]


@pytest.mark.parametrize("granularity", ["day", "week", "month", "quarter", "year"])
def test_slash_date_buckets_match_pandas_semantics(granularity):
    df = pd.DataFrame(
        {
            "sold_on": [
                "11/1/2022",
                "11/2/2022 14:30",
                "11/6/2022",
                "11/7/2022",
                "12/31/2022",
                "1/1/2023",
                "25/12/2022",  # month-first impossible -> day-first
                "3/4/23",  # two-digit year
                "2023/6/15",
                "2023-07-04",
                "garbage",
            ],
            "amount": [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 1024.0],
        }
    )

    duckdb_result = execute_plan_duckdb(
        DuckDBStorage(df.copy()), _time_plan("sold_on", granularity)
    )
    pandas_result = execute_plan(df.copy(), _time_plan("sold_on", granularity))

    assert len(duckdb_result) > 0
    pd.testing.assert_frame_equal(
        _normalize(duckdb_result, "sold_on"),
        _normalize(pandas_result, "sold_on"),
        check_dtype=False,
    )
