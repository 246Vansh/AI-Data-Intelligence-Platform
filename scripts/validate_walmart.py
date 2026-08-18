from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data
from data_engine.validator import validate_walmart_data


INPUT_PATH = "data/raw/Walmart_Sales.csv"


def main():

    print("Loading dataset...")

    df = load_csv(INPUT_PATH)

    print("Cleaning dataset...")

    cleaned_df = clean_walmart_data(df)

    print("Validating dataset...")

    validation = validate_walmart_data(cleaned_df)

    print()
    print("=" * 50)
    print("DATA VALIDATION REPORT")
    print("=" * 50)

    print(f"\nDataset valid: {validation['valid']}")

    print(
        f"Duplicate rows: "
        f"{validation['duplicate_rows']}"
    )

    print("\nDate range:")

    print(
        f"From: {validation['date_range']['minimum']}"
    )

    print(
        f"To: {validation['date_range']['maximum']}"
    )

    print("\nIssues:")

    if not validation["issues"]:
        print("None")

    else:
        for issue in validation["issues"]:
            print(issue)

    print("\nWarnings:")

    if not validation["warnings"]:
        print("None")

    else:
        for warning in validation["warnings"]:
            print(warning)


if __name__ == "__main__":
    main()