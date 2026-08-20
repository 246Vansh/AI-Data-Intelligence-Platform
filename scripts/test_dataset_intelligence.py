import pandas as pd

from data_engine.dataset_intelligence import (
    build_dataset_intelligence,
)


def print_section(title: str):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def main():

    print("=" * 60)
    print("TESTING DATASET INTELLIGENCE")
    print("=" * 60)

    # =====================================================
    # TEST 1 — Basic Dataset
    # =====================================================

    print_section("TEST 1 — Basic Dataset")

    df = pd.DataFrame(
        {
            "customer": [
                "Alice",
                "Bob",
                "Charlie",
                "Alice",
            ],
            "age": [
                25,
                31,
                42,
                28,
            ],
            "revenue": [
                100.0,
                250.0,
                175.0,
                125.0,
            ],
            "active": [
                True,
                True,
                False,
                True,
            ],
        }
    )

    intelligence = build_dataset_intelligence(df)

    print(
        "ROWS:",
        intelligence["shape"]["rows"],
    )

    print(
        "COLUMNS:",
        intelligence["shape"]["columns"],
    )

    assert intelligence["shape"]["rows"] == 4
    assert intelligence["shape"]["columns"] == 4

    print("RESULT: passed")

    # =====================================================
    # TEST 2 — Metadata
    # =====================================================

    print_section("TEST 2 — Metadata")

    metadata = intelligence["metadata"]

    assert "columns" in metadata

    assert "customer" in metadata["columns"]

    assert "revenue" in metadata["columns"]

    print(
        "METADATA COLUMNS:",
        list(metadata["columns"].keys()),
    )

    print("RESULT: passed")

    # =====================================================
    # TEST 3 — Profile
    # =====================================================

    print_section("TEST 3 — Profile")

    profile = intelligence["profile"]

    assert profile is not None

    print(
        "PROFILE TYPE:",
        type(profile).__name__,
    )

    print("RESULT: passed")

    # =====================================================
    # TEST 4 — Quality
    # =====================================================

    print_section("TEST 4 — Quality")

    quality = intelligence["quality"]

    assert quality is not None

    print(
        "QUALITY STATUS:",
        quality["status"],
    )

    print(
        "ISSUES:",
        len(quality["issues"]),
    )

    print("RESULT: passed")

    # =====================================================
    # TEST 5 — Missing Values
    # =====================================================

    print_section("TEST 5 — Missing Values")

    df_missing = pd.DataFrame(
        {
            "name": [
                "Alice",
                None,
                "Charlie",
                "David",
            ],
            "revenue": [
                100,
                200,
                300,
                400,
            ],
        }
    )

    intelligence_missing = build_dataset_intelligence(df_missing)

    quality_missing = intelligence_missing["quality"]

    print(
        "QUALITY STATUS:",
        quality_missing["status"],
    )

    assert quality_missing["status"] in {"warning", "invalid"}

    assert any(issue["type"] == "missing_values" for issue in quality_missing["issues"])

    print("RESULT: passed")

    # =====================================================
    # TEST 6 — Dataset Independence
    # =====================================================

    print_section("TEST 6 — Dataset Independence")

    df_other = pd.DataFrame(
        {
            "temperature": [
                20.5,
                21.0,
                19.5,
            ],
            "city": [
                "Delhi",
                "Mumbai",
                "Pune",
            ],
            "rain": [
                True,
                False,
                True,
            ],
        }
    )

    other_intelligence = build_dataset_intelligence(df_other)

    print(
        "ROWS:",
        other_intelligence["shape"]["rows"],
    )

    print(
        "COLUMNS:",
        other_intelligence["shape"]["columns"],
    )

    print(
        "COLUMNS FOUND:",
        list(other_intelligence["metadata"]["columns"].keys()),
    )

    assert other_intelligence["shape"]["rows"] == 3

    assert other_intelligence["shape"]["columns"] == 3

    assert set(other_intelligence["metadata"]["columns"]) == {
        "temperature",
        "city",
        "rain",
    }

    print("RESULT: passed")

    # =====================================================
    # TEST 7 — Empty Dataset
    # =====================================================

    print_section("TEST 7 — Empty Dataset")

    empty_df = pd.DataFrame(
        columns=[
            "name",
            "revenue",
        ]
    )

    empty_intelligence = build_dataset_intelligence(empty_df)

    print(
        "ROWS:",
        empty_intelligence["shape"]["rows"],
    )

    print(
        "COLUMNS:",
        empty_intelligence["shape"]["columns"],
    )

    print(
        "QUALITY STATUS:",
        empty_intelligence["quality"]["status"],
    )

    assert empty_intelligence["shape"]["rows"] == 0

    assert empty_intelligence["quality"]["status"] == "invalid"

    print("RESULT: passed")

    # =====================================================
    # FINAL
    # =====================================================

    print()
    print("=" * 60)
    print("ALL DATASET INTELLIGENCE TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
