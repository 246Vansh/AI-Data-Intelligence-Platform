from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data
from data_engine.query_engine import analyze


INPUT_PATH = "data/raw/Walmart_Sales.csv"


def main():

    print("Loading dataset...")

    df = load_csv(
        INPUT_PATH
    )

    print("Cleaning dataset...")

    df = clean_walmart_data(
        df
    )

    print()
    print("=" * 60)
    print("TOTAL WEEKLY SALES")
    print("=" * 60)

    result = analyze(
        df=df,
        group_by=[],
        metric="Weekly_Sales",
        aggregation="sum",
    )

    print(result)

    print()
    print("=" * 60)
    print("AVERAGE WEEKLY SALES")
    print("=" * 60)

    result = analyze(
        df=df,
        group_by=[],
        metric="Weekly_Sales",
        aggregation="mean",
    )

    print(result)


if __name__ == "__main__":
    main()