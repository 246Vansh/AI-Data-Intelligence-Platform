import pandas as pd

from data_engine.insight_engine import (
    build_deterministic_insights,
)


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

    print(context)


def main():

    print("=" * 60)
    print("TESTING DETERMINISTIC INSIGHT ENGINE")
    print("=" * 60)

    # =====================================================
    # TEST 1 — Walmart-style data
    # =====================================================

    walmart_df = pd.DataFrame(
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
        name="TEST 1 — Walmart Dataset",
        df=walmart_df,
        metric_column="sum_Weekly_Sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 2 — Increasing
    # =====================================================

    increasing_df = pd.DataFrame(
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
        df=increasing_df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 3 — Decreasing
    # =====================================================

    decreasing_df = pd.DataFrame(
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
        df=decreasing_df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 4 — Mixed
    # =====================================================

    mixed_df = pd.DataFrame(
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
        df=mixed_df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 5 — Insufficient Data
    # =====================================================

    single_row_df = pd.DataFrame(
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
        name="TEST 5 — Single Row",
        df=single_row_df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 6 — Empty Dataset
    # =====================================================

    empty_df = pd.DataFrame(
        columns=[
            "Date",
            "sales",
        ]
    )

    run_test(
        name="TEST 6 — Empty Dataset",
        df=empty_df,
        metric_column="sales",
        group_by=["Date"],
    )

    # =====================================================
    # TEST 7 — Stable
    # =====================================================

    stable_df = pd.DataFrame(
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
        name="TEST 7 — Stable Trend",
        df=stable_df,
        metric_column="sales",
        group_by=["Date"],
    )


if __name__ == "__main__":
    main()
