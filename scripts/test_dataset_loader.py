from pathlib import Path

from data_engine.dataset_loader import (
    DatasetLoadError,
    load_csv,
)


def main():

    print("=" * 60)
    print("TESTING DATASET LOADER")
    print("=" * 60)

    # -----------------------------------------
    # Test 1 — Valid CSV
    # -----------------------------------------

    dataset_path = Path("data/raw/Walmart_Sales.csv")

    print("\nTEST 1 — Valid CSV")

    df = load_csv(dataset_path)

    print(f"ROWS    : {len(df)}")

    print(f"COLUMNS : {len(df.columns)}")

    print(f"SHAPE   : {df.shape}")

    # -----------------------------------------
    # Test 2 — File does not exist
    # -----------------------------------------

    print("\nTEST 2 — Missing file")

    try:
        load_csv("data/raw/does_not_exist.csv")

        print("ERROR: expected failure")

    except DatasetLoadError as exc:
        print(f"EXPECTED ERROR: {exc}")

    # -----------------------------------------
    # Test 3 — Result is DataFrame
    # -----------------------------------------

    print("\nTEST 3 — DataFrame result")

    import pandas as pd

    assert isinstance(
        df,
        pd.DataFrame,
    )

    print("RESULT: DataFrame")

    # -----------------------------------------
    # Finished
    # -----------------------------------------

    print("\n" + "=" * 60)
    print("ALL DATASET LOADER TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
