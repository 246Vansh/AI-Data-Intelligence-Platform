from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data


INPUT_PATH = "data/raw/Walmart_Sales.csv"
OUTPUT_PATH = "data/processed/Walmart_Sales_clean.csv"


def main():
    print("Loading raw dataset...")

    df = load_csv(INPUT_PATH)

    print(f"Original rows: {len(df)}")

    print("\nCleaning dataset...")

    cleaned_df = clean_walmart_data(df)

    print("Cleaning completed.")

    print("\nColumn types after cleaning:")

    for column, dtype in cleaned_df.dtypes.items():
        print(f"- {column}: {dtype}")

    print("\nSaving cleaned dataset...")

    cleaned_df.to_csv(
        OUTPUT_PATH,
        index=False
    )

    print(f"Saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()