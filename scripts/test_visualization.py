import pandas as pd

from data_engine.visualization import (
    create_visualization_spec,
)


def main():

    print("=" * 60)
    print("TESTING VISUALIZATION ENGINE")
    print("=" * 60)

    # =====================================================
    # TEST DATA
    # =====================================================

    df = pd.DataFrame(
        {
            "Store": [1, 2, 3],
            "Weekly_Sales": [100, 200, 150],
        }
    )

    # =====================================================
    # TEST 1 — TABLE
    # =====================================================

    print("\nTEST 1 — Table")

    result = create_visualization_spec(
        result=df,
        visualization_type="table",
    )

    print("RESULT:", result)

    assert result["type"] == "table"
    assert result["title"] == "Analysis Results"
    assert result["encoding"]["columns"] == [
        "Store",
        "Weekly_Sales",
    ]

    print("RESULT: passed")

    # =====================================================
    # TEST 2 — BAR
    # =====================================================

    print("\nTEST 2 — Bar")

    result = create_visualization_spec(
        result=df,
        visualization_type="bar",
    )

    print("RESULT:", result)

    assert result["type"] == "bar"
    assert result["encoding"]["x"] == "Store"
    assert result["encoding"]["y"] == "Weekly_Sales"

    print("RESULT: passed")

    # =====================================================
    # TEST 3 — LINE
    # =====================================================

    print("\nTEST 3 — Line")

    result = create_visualization_spec(
        result=df,
        visualization_type="line",
    )

    print("RESULT:", result)

    assert result["type"] == "line"

    print("RESULT: passed")

    # =====================================================
    # TEST 4 — PIE
    # =====================================================

    print("\nTEST 4 — Pie")

    result = create_visualization_spec(
        result=df,
        visualization_type="pie",
    )

    print("RESULT:", result)

    assert result["type"] == "pie"

    print("RESULT: passed")

    # =====================================================
    # TEST 5 — SCATTER
    # =====================================================

    print("\nTEST 5 — Scatter")

    result = create_visualization_spec(
        result=df,
        visualization_type="scatter",
    )

    print("RESULT:", result)

    assert result["type"] == "scatter"

    print("RESULT: passed")

    # =====================================================
    # TEST 6 — CUSTOM TITLE
    # =====================================================

    print("\nTEST 6 — Custom Title")

    result = create_visualization_spec(
        result=df,
        visualization_type="bar",
        title="Top Stores",
    )

    print("RESULT:", result)

    assert result["title"] == "Top Stores"

    print("RESULT: passed")

    # =====================================================
    # TEST 7 — INVALID VISUALIZATION
    # =====================================================

    print("\nTEST 7 — Invalid Visualization")

    try:
        create_visualization_spec(
            result=df,
            visualization_type="invalid",
        )

        raise AssertionError("Expected ValueError")

    except ValueError as exc:
        print("EXPECTED ERROR:", exc)

    print("RESULT: passed")

    # =====================================================
    # TEST 8 — CHART WITH ONE COLUMN
    # =====================================================

    print("\nTEST 8 — Insufficient Chart Columns")

    single_column_df = pd.DataFrame(
        {
            "Sales": [100, 200, 300],
        }
    )

    try:
        create_visualization_spec(
            result=single_column_df,
            visualization_type="bar",
        )

        raise AssertionError("Expected ValueError")

    except ValueError as exc:
        print("EXPECTED ERROR:", exc)

    print("RESULT: passed")

    # =====================================================
    # COMPLETE
    # =====================================================

    print("\n" + "=" * 60)
    print("ALL VISUALIZATION TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
