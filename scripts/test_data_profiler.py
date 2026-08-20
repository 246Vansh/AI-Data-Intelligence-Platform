import pandas as pd

from data_engine.dataset_profile import (
    profile_dataset,
)


def print_section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def main():

    print_section("TESTING DATA PROFILER")

    # =====================================================
    # TEST 1 — Basic mixed dataset
    # =====================================================

    print_section("TEST 1 — Mixed Dataset")

    df = pd.DataFrame(
        {
            "customer": ["Alice", "Bob", "Charlie", "Alice", None],
            "age": [25, 31, 42, None, 29],
            "revenue": [100.5, 250.0, 175.5, 100.5, None],
            "active": [True, False, True, True, False],
        }
    )

    profile = profile_dataset(df)

    print(
        "ROWS:",
        profile["row_count"],
    )

    print(
        "COLUMNS:",
        profile["column_count"],
    )

    print(
        "DUPLICATES:",
        profile["duplicate_row_count"],
    )

    print(
        "CUSTOMER TYPE:",
        profile["columns"]["customer"]["data_type"],
    )

    print(
        "AGE TYPE:",
        profile["columns"]["age"]["data_type"],
    )

    print(
        "REVENUE TYPE:",
        profile["columns"]["revenue"]["data_type"],
    )

    print(
        "ACTIVE TYPE:",
        profile["columns"]["active"]["data_type"],
    )

    # =====================================================
    # TEST 2 — Missing values
    # =====================================================

    print_section("TEST 2 — Missing Values")

    age_profile = profile["columns"]["age"]

    print(
        "AGE MISSING:",
        age_profile["missing_count"],
    )

    print(
        "AGE MISSING %:",
        age_profile["missing_percentage"],
    )

    assert age_profile["missing_count"] == 1

    # =====================================================
    # TEST 3 — Numeric statistics
    # =====================================================

    print_section("TEST 3 — Numeric Statistics")

    revenue_stats = profile["columns"]["revenue"]["statistics"]

    print(
        "MIN:",
        revenue_stats["min"],
    )

    print(
        "MAX:",
        revenue_stats["max"],
    )

    print(
        "MEAN:",
        revenue_stats["mean"],
    )

    print(
        "MEDIAN:",
        revenue_stats["median"],
    )

    # =====================================================
    # TEST 4 — Categorical values
    # =====================================================

    print_section("TEST 4 — Top Categorical Values")

    customer_profile = profile["columns"]["customer"]

    print(
        "TOP VALUES:",
        customer_profile["top_values"],
    )

    # =====================================================
    # TEST 5 — Duplicate detection
    # =====================================================

    print_section("TEST 5 — Duplicate Detection")

    duplicate_df = pd.DataFrame(
        {
            "product": ["A", "B", "A"],
            "value": [10, 20, 10],
        }
    )

    duplicate_profile = profile_dataset(duplicate_df)

    print(
        "DUPLICATES:",
        duplicate_profile["duplicate_row_count"],
    )

    assert duplicate_profile["duplicate_row_count"] == 1

    # =====================================================
    # TEST 6 — Completely different dataset
    # =====================================================

    print_section("TEST 6 — Dataset Independence")

    df2 = pd.DataFrame(
        {
            "temperature": [20.5, 21.2, 19.8],
            "city": ["Delhi", "Mumbai", "Delhi"],
            "rain": [True, False, True],
        }
    )

    profile2 = profile_dataset(df2)

    print(
        "ROWS:",
        profile2["row_count"],
    )

    print(
        "COLUMNS:",
        profile2["column_count"],
    )

    print(
        "COLUMNS FOUND:",
        list(profile2["columns"].keys()),
    )

    assert profile2["row_count"] == 3

    assert profile2["column_count"] == 3

    print_section("ALL DATA PROFILER TESTS PASSED")


if __name__ == "__main__":
    main()
