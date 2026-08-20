from backend.dependencies import (
    get_walmart_data,
)

from data_engine.analysis_pipeline import (
    run_analysis_pipeline,
)


def print_section(title: str):

    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def main():

    print("=" * 60)
    print("TESTING ANALYSIS PIPELINE")
    print("=" * 60)

    # =====================================================
    # Load dataset
    # =====================================================

    print_section("LOADING DATASET")

    df = get_walmart_data()

    print(
        "ROWS:",
        len(df),
    )

    print(
        "COLUMNS:",
        len(df.columns),
    )

    # =====================================================
    # TEST 1 — Fast Planner
    # =====================================================

    print_section("TEST 1 — FAST PLANNER PATH")

    question = "Show the top 5 stores by average Weekly_Sales"

    result = run_analysis_pipeline(
        df=df,
        question=question,
    )

    print(
        "PLANNER:",
        result.planner_type,
    )

    print(
        "FALLBACK:",
        result.fallback_to_ai,
    )

    print(
        "PLAN:",
        result.plan,
    )

    print(
        "RESULT ROWS:",
        result.analysis_result["row_count"],
    )

    assert result.planner_type == "fast"

    assert result.fallback_to_ai is False

    assert result.plan.metric == "Weekly_Sales"

    assert result.plan.group_by == ["Store"]

    print("RESULT: passed")

    # =====================================================
    # TEST 2 — AI Fallback
    # =====================================================

    print_section("TEST 2 — AI FALLBACK PATH")

    question = "Show the top 5 stores by average Weekly_Sales during holidays."

    result = run_analysis_pipeline(
        df=df,
        question=question,
    )

    print(
        "PLANNER:",
        result.planner_type,
    )

    print(
        "FALLBACK:",
        result.fallback_to_ai,
    )

    print(
        "PLAN:",
        result.plan,
    )

    print(
        "RESULT ROWS:",
        result.analysis_result["row_count"],
    )

    assert result.planner_type == "claude"

    assert result.fallback_to_ai is True

    assert result.plan.metric == "Weekly_Sales"

    assert result.plan.group_by == ["Store"]

    assert result.plan.aggregation == "mean"

    print("RESULT: passed")

    # =====================================================
    # TEST 3 — Dataset Independence
    # =====================================================

    print_section("TEST 3 — DATASET INDEPENDENCE")

    import pandas as pd

    other_df = pd.DataFrame(
        {
            "region": [
                "North",
                "South",
                "North",
                "West",
            ],
            "revenue": [
                100,
                200,
                300,
                150,
            ],
        }
    )

    result = run_analysis_pipeline(
        df=other_df,
        question=("Show the top 2 regions by revenue"),
    )

    print(
        "PLANNER:",
        result.planner_type,
    )

    print(
        "PLAN:",
        result.plan,
    )

    print(
        "RESULT:",
        result.analysis_result,
    )

    assert result.plan.metric == "revenue"

    assert result.plan.group_by == ["region"]

    assert result.plan.limit == 2

    print("RESULT: passed")

    # =====================================================
    # FINAL
    # =====================================================

    print()
    print("=" * 60)
    print("ALL ANALYSIS PIPELINE TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
