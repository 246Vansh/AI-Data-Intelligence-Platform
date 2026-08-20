import pandas as pd

from data_engine.data_quality import (
    check_data_quality,
)


def print_section(
    title: str,
) -> None:

    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def main():

    print_section("TESTING DATA QUALITY ENGINE")

    # =====================================================
    # TEST 1 — Healthy dataset
    # =====================================================

    print_section("TEST 1 — Healthy Dataset")

    df = pd.DataFrame(
        {
            "product": [
                "A",
                "B",
                "C",
                "D",
                "E",
            ],
            "revenue": [
                100,
                200,
                150,
                300,
                250,
            ],
            "active": [
                True,
                False,
                True,
                False,
                True,
            ],
        }
    )

    result = check_data_quality(df)

    print(
        "STATUS:",
        result["status"],
    )

    print(
        "ISSUES:",
        result["issue_count"],
    )

    assert result["status"] == "healthy"

    # =====================================================
    # TEST 2 — Missing values
    # =====================================================

    print_section("TEST 2 — Missing Values")

    df = pd.DataFrame(
        {
            "name": [
                "A",
                "B",
                None,
                "D",
                "E",
            ],
            "value": [
                10,
                20,
                30,
                40,
                50,
            ],
        }
    )

    result = check_data_quality(df)

    print(
        "STATUS:",
        result["status"],
    )

    print(
        "ISSUES:",
        result["issues"],
    )

    assert any(issue["type"] == "missing_values" for issue in result["issues"])

    # =====================================================
    # TEST 3 — Duplicate rows
    # =====================================================

    print_section("TEST 3 — Duplicate Rows")

    df = pd.DataFrame(
        {
            "product": [
                "A",
                "B",
                "A",
            ],
            "value": [
                10,
                20,
                10,
            ],
        }
    )

    result = check_data_quality(df)

    print(
        "STATUS:",
        result["status"],
    )

    print(
        "ISSUES:",
        result["issues"],
    )

    assert any(issue["type"] == "duplicate_rows" for issue in result["issues"])

    # =====================================================
    # TEST 4 — Constant column
    # =====================================================

    print_section("TEST 4 — Constant Column")

    df = pd.DataFrame(
        {
            "category": [
                "A",
                "B",
                "C",
                "D",
            ],
            "constant": [
                1,
                1,
                1,
                1,
            ],
        }
    )

    result = check_data_quality(df)

    print(
        "STATUS:",
        result["status"],
    )

    print(
        "ISSUES:",
        result["issues"],
    )

    assert any(issue["type"] == "constant_column" for issue in result["issues"])

    # =====================================================
    # TEST 5 — High cardinality
    # =====================================================

    print_section("TEST 5 — High Cardinality")

    df = pd.DataFrame(
        {
            "transaction_id": range(100),
            "value": range(100),
        }
    )

    result = check_data_quality(df)

    print(
        "STATUS:",
        result["status"],
    )

    print(
        "ISSUES:",
        result["issues"],
    )

    assert any(issue["type"] == "high_cardinality" for issue in result["issues"])

    # =====================================================
    # TEST 6 — Numeric outliers
    # =====================================================

    print_section("TEST 6 — Numeric Outliers")

    df = pd.DataFrame(
        {
            "value": [
                10,
                11,
                12,
                13,
                14,
                1000,
            ]
        }
    )

    result = check_data_quality(df)

    print(
        "STATUS:",
        result["status"],
    )

    print(
        "ISSUES:",
        result["issues"],
    )

    assert any(issue["type"] == "numeric_outliers" for issue in result["issues"])

    # =====================================================
    # TEST 7 — Empty dataset
    # =====================================================

    print_section("TEST 7 — Empty Dataset")

    df = pd.DataFrame(
        columns=[
            "name",
            "value",
        ]
    )

    result = check_data_quality(df)

    print(
        "STATUS:",
        result["status"],
    )

    print(
        "ISSUES:",
        result["issues"],
    )

    assert result["status"] == "invalid"

    # =====================================================
    # FINAL
    # =====================================================

    print_section("ALL DATA QUALITY TESTS PASSED")


if __name__ == "__main__":
    main()
