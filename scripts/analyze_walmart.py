from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data
from data_engine.analytics import (
    sales_summary,
    store_sales,
    monthly_sales,
    holiday_sales_comparison,
)


INPUT_PATH = "data/raw/Walmart_Sales.csv"


def main():

    df = load_csv(INPUT_PATH)

    df = clean_walmart_data(df)

    print("=" * 50)
    print("SALES SUMMARY")
    print("=" * 50)

    summary = sales_summary(df)

    for name, value in summary.items():
        print(f"{name}: {value:,.2f}")

    print("\n")
    print("=" * 50)
    print("TOP STORES")
    print("=" * 50)

    top_stores = store_sales(df)

    print(
        top_stores.head(10).to_string(index=False)
    )

    print("\n")
    print("=" * 50)
    print("MONTHLY SALES")
    print("=" * 50)

    monthly = monthly_sales(df)

    print(
        monthly.head(20).to_string(index=False)
    )

    print("\n")
    print("=" * 50)
    print("HOLIDAY SALES COMPARISON")
    print("=" * 50)

    holiday = holiday_sales_comparison(df)

    print(
        holiday.to_string(index=False)
    )


if __name__ == "__main__":
    main()