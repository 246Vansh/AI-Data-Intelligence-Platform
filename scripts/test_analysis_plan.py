from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data

from data_engine.analysis_plan import (
    AnalysisPlan,
    FilterCondition,
)

from data_engine.plan_executor import execute_plan


INPUT_PATH = "data/raw/Walmart_Sales.csv"


def main():

    # -----------------------------------------
    # Load and clean
    # -----------------------------------------

    print("Loading dataset...")

    df = load_csv(INPUT_PATH)

    df = clean_walmart_data(df)

    print(
        f"Loaded {len(df):,} rows."
    )

    # -----------------------------------------
    # Create analysis plan
    # -----------------------------------------

    plan = AnalysisPlan(

        filters=[
            FilterCondition(
                column="Holiday_Flag",
                operator="=",
                value=1,
            )
        ],

        group_by=["Store"],

        metric="Weekly_Sales",

        aggregation="mean",

        sort="desc",

        limit=5,

        visualization="bar",
    )

    # -----------------------------------------
    # Display plan
    # -----------------------------------------

    print()
    print("=" * 60)
    print("ANALYSIS PLAN")
    print("=" * 60)

    print("Filter:")
    print("  Holiday_Flag = 1")

    print("Group By:")
    print("  Store")

    print("Metric:")
    print("  Weekly_Sales")

    print("Aggregation:")
    print("  mean")

    print("Sort:")
    print("  desc")

    print("Limit:")
    print("  5")

    print("Visualization:")
    print("  bar")

    # -----------------------------------------
    # Execute
    # -----------------------------------------

    print()
    print("=" * 60)
    print("RESULT")
    print("=" * 60)

    result = execute_plan(
        df,
        plan,
    )

    print(
        result.to_string(index=False)
    )


if __name__ == "__main__":
    main()