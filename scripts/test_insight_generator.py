from pprint import pprint

import pandas as pd

from data_engine.insight_engine import build_deterministic_insights
from data_engine.insight_generator import build_insight_response
from ai.insight_validator import validate_insights


def run_test(
    name: str,
    df: pd.DataFrame,
    metric_column: str,
    group_by: list[str],
):
    print("\n" + "=" * 60)
    print(name)
    print("=" * 60)

    context = build_deterministic_insights(
        result=df,
        metric_column=metric_column,
        group_by=group_by,
    )

    print("\nDETERMINISTIC CONTEXT:")
    pprint(context)

    response = build_insight_response(context)

    print("\nGENERATED INSIGHTS:")

    for insight in response.insights:
        print(f"- [{insight.type}] {insight.title}")

    validate_insights(
        response,
        context,
    )

    print("\nVALIDATION: PASSED")


def main():

    # =====================================================
    # TEST 1 — Walmart-like data
    # =====================================================

    df = pd.DataFrame(
        {
            "Date": [
                "2010-02-01",
                "2010-03-01",
                "2010-04-01",
                "2010-12-01",
            ],
            "sum_Weekly_Sales": [
                190332983.04,
                181919802.50,
                231412368.05,
                288760532.72,
            ],
        }
    )

    run_test(
        name="TEST 1 — Walmart-like Dataset",
        df=df,
        metric_column="sum_Weekly_Sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 2 — Increasing
    # =====================================================

    df = pd.DataFrame(
        {
            "Date": [
                "2020-01-01",
                "2020-02-01",
                "2020-03-01",
            ],
            "sales": [
                100,
                200,
                300,
            ],
        }
    )

    run_test(
        name="TEST 2 — Increasing Trend",
        df=df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 3 — Decreasing
    # =====================================================

    df = pd.DataFrame(
        {
            "Date": [
                "2020-01-01",
                "2020-02-01",
                "2020-03-01",
            ],
            "sales": [
                300,
                200,
                100,
            ],
        }
    )

    run_test(
        name="TEST 3 — Decreasing Trend",
        df=df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 4 — Mixed
    # =====================================================

    df = pd.DataFrame(
        {
            "Date": [
                "2020-01-01",
                "2020-02-01",
                "2020-03-01",
            ],
            "sales": [
                100,
                300,
                200,
            ],
        }
    )

    run_test(
        name="TEST 4 — Mixed Trend",
        df=df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 5 — Stable
    # =====================================================

    df = pd.DataFrame(
        {
            "Date": [
                "2020-01-01",
                "2020-02-01",
                "2020-03-01",
            ],
            "sales": [
                100,
                100,
                100,
            ],
        }
    )

    run_test(
        name="TEST 5 — Stable Trend",
        df=df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 6 — Single row
    # =====================================================

    df = pd.DataFrame(
        {
            "Date": [
                "2020-01-01",
            ],
            "sales": [
                100,
            ],
        }
    )

    run_test(
        name="TEST 6 — Single Row",
        df=df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 7 — Empty
    # =====================================================

    df = pd.DataFrame(
        columns=[
            "Date",
            "sales",
        ]
    )

    run_test(
        name="TEST 7 — Empty Dataset",
        df=df,
        metric_column="sales",
        group_by=["Date"],
    )


if __name__ == "__main__":
    main()
