import pandas as pd

from ai.insights import generate_insights

from data_engine.insight_context import (
    build_insight_context,
)

from ai.insight_validator import (
    validate_insights,
)


def main():

    print("=" * 60)
    print("TESTING INSIGHT SERVICE")
    print("=" * 60)

    question = "Show me monthly sales trends."

    result = {
        "columns": [
            "Date",
            "sum_Weekly_Sales",
        ],
        "rows": [
            {
                "Date": "2010-02-01",
                "sum_Weekly_Sales": 190332983.04,
            },
            {
                "Date": "2010-03-01",
                "sum_Weekly_Sales": 181919802.50,
            },
            {
                "Date": "2010-04-01",
                "sum_Weekly_Sales": 231412368.05,
            },
            {
                "Date": "2010-12-01",
                "sum_Weekly_Sales": 288760532.72,
            },
        ],
        "row_count": 4,
    }

    print()
    print("AI PROVIDER:")
    print("Using provider from AI_PROVIDER")

    # -----------------------------------------
    # Build verified insight context
    # -----------------------------------------

    result_df = pd.DataFrame(result["rows"])

    insight_context = build_insight_context(
        result=result_df,
        metric_column="sum_Weekly_Sales",
        group_by=["Date"],
    )

    print()
    print("VERIFIED INSIGHT CONTEXT:")
    print(insight_context)

    # -----------------------------------------
    # Generate insights
    # -----------------------------------------

    print()
    print("GENERATING INSIGHTS...")

    response = generate_insights(
        question=question,
        result=result,
        context=insight_context,
    )

    validate_insights(response, insight_context)

    print()
    print("=" * 60)
    print("INSIGHTS")
    print("=" * 60)

    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
