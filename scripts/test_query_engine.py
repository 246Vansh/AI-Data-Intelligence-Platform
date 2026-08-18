from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data
from data_engine.query_engine import analyze


INPUT_PATH = "data/raw/Walmart_Sales.csv"


def main():

    df = load_csv(INPUT_PATH)

    df = clean_walmart_data(df)

    print("=" * 60)
    print("TOP 10 STORES BY TOTAL SALES")
    print("=" * 60)

    result = analyze(
        df,
        group_by=["Store"],
        metric="Weekly_Sales",
        aggregation="sum",
        sort="desc",
        limit=10,
    )

    print(result.to_string(index=False))

    print()
    print("=" * 60)
    print("TOP 10 STORES BY AVERAGE SALES")
    print("=" * 60)

    result = analyze(
        df,
        group_by=["Store"],
        metric="Weekly_Sales",
        aggregation="mean",
        sort="desc",
        limit=10,
    )

    print(result.to_string(index=False))


if __name__ == "__main__":
    main()