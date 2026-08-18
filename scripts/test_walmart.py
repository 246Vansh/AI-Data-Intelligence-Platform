from data_engine.loader import load_csv
from data_engine.profiler import profile_dataset


DATASET_PATH = "data/raw/Walmart_Sales.csv"


def main():
    print("Loading dataset...")

    df = load_csv(DATASET_PATH)

    print("Dataset loaded successfully!")
    print()

    profile = profile_dataset(df)

    print("=" * 50)
    print("DATASET PROFILE")
    print("=" * 50)

    print(f"Rows: {profile['rows']}")
    print(f"Columns: {profile['columns']}")
    print(f"Duplicate rows: {profile['duplicate_rows']}")

    memory_mb = (
        profile["memory_usage_bytes"] / (1024 * 1024)
    )

    print(f"Memory usage: {memory_mb:.2f} MB")

    print("\nCOLUMN ANALYSIS")
    print("-" * 50)

    for column, details in profile["column_details"].items():

        print(f"\n{column}")

        print(
            f"  Type: {details['data_type']}"
        )

        print(
            f"  Missing: "
            f"{details['missing_count']} "
            f"({details['missing_percentage']}%)"
        )

        print(
            f"  Unique values: "
            f"{details['unique_values']}"
        )


if __name__ == "__main__":
    main()