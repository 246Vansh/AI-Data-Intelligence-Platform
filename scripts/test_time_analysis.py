from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data

from data_engine.analysis_plan import (
    AnalysisPlan,
)

from data_engine.plan_validator import (
    validate_plan,
)

from data_engine.plan_executor import (
    execute_plan,
)


INPUT_PATH = (
    "data/raw/Walmart_Sales.csv"
)


def main():

    print("Loading dataset...")

    df = load_csv(
        INPUT_PATH
    )

    print("Cleaning dataset...")

    df = clean_walmart_data(
        df
    )

    # -----------------------------------------
    # Create monthly analysis plan
    # -----------------------------------------

    plan = AnalysisPlan(

        group_by=[
            "Date"
        ],

        metric="Weekly_Sales",

        aggregation="sum",

        sort="asc",
        
        sort_by="time",

        time_granularity="month",

    )

    print()
    print("=" * 60)
    print("VALIDATING PLAN")
    print("=" * 60)

    validate_plan(
        df,
        plan,
    )

    print("PLAN IS VALID.")

    print()
    print("=" * 60)
    print("EXECUTING MONTHLY ANALYSIS")
    print("=" * 60)

    result = execute_plan(
        df,
        plan,
    )

    print(
        result.head(20).to_string(
            index=False
        )
    )


if __name__ == "__main__":
    main()