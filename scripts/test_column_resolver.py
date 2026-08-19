from data_engine.column_resolver import (
    normalize_column_name,
    resolve_column,
)


def main():

    columns = {
        "Weekly_Sales": {
            "role": "metric",
        },
        "Store": {
            "role": "dimension",
        },
        "Sales_Growth": {
            "role": "metric",
        },
        "Region": {
            "role": "categorical",
        },
    }

    print("=" * 60)
    print("TESTING COLUMN RESOLVER")
    print("=" * 60)

    # -----------------------------------------------------
    # TEST 1
    # -----------------------------------------------------

    print("\nTEST 1 — Exact column")

    result = resolve_column(
        "Weekly_Sales",
        columns,
        allowed_roles={"metric"},
    )

    print("RESULT:", result)

    assert result == "Weekly_Sales"

    # -----------------------------------------------------
    # TEST 2
    # -----------------------------------------------------

    print("\nTEST 2 — Case insensitive")

    result = resolve_column(
        "WEEKLY SALES",
        columns,
        allowed_roles={"metric"},
    )

    print("RESULT:", result)

    assert result == "Weekly_Sales"

    # -----------------------------------------------------
    # TEST 3
    # -----------------------------------------------------

    print("\nTEST 3 — Underscore / space normalization")

    result = resolve_column(
        "Show total weekly sales",
        columns,
        allowed_roles={"metric"},
    )

    print("RESULT:", result)

    assert result == "Weekly_Sales"

    # -----------------------------------------------------
    # TEST 4
    # -----------------------------------------------------

    print("\nTEST 4 — Dimension")

    result = resolve_column(
        "Show Store",
        columns,
        allowed_roles={"dimension", "categorical"},
    )

    print("RESULT:", result)

    assert result == "Store"

    # -----------------------------------------------------
    # TEST 5
    # -----------------------------------------------------

    print("\nTEST 5 — Unknown column")

    result = resolve_column(
        "Show revenue",
        columns,
        allowed_roles={"metric"},
    )

    print("RESULT:", result)

    assert result is None

    # -----------------------------------------------------
    # TEST 6
    # -----------------------------------------------------

    print("\nTEST 6 — Ambiguous column")

    ambiguous_columns = {
        "Sales": {
            "role": "metric",
        },
        "Total_Sales": {
            "role": "metric",
        },
    }

    result = resolve_column(
        "Show sales",
        ambiguous_columns,
        allowed_roles={"metric"},
    )

    print("RESULT:", result)

    # Depending on the exact phrase matching,
    # this must not silently select a random column.
    assert result in {
        None,
        "Sales",
    }

    # -----------------------------------------------------
    # TEST 7
    # -----------------------------------------------------

    print("\nTEST 7 — Normalization")

    assert normalize_column_name("Weekly_Sales") == "weekly sales"

    assert normalize_column_name("WEEKLY-SALES") == "weekly sales"

    print("RESULT: normalization passed")

    # -----------------------------------------------------
    # COMPLETE
    # -----------------------------------------------------

    print()
    print("=" * 60)
    print("ALL COLUMN RESOLVER TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
