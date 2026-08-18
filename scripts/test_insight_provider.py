from ai.insight_providers.claude_insight_provider import (
    ClaudeInsightProvider,
)


def main():

    print("=" * 60)
    print("TESTING CLAUDE INSIGHT PROVIDER")
    print("=" * 60)

    question = (
        "Show me monthly sales trends."
    )

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
    print("QUESTION:")
    print(question)

    print()
    print("GENERATING INSIGHTS...")

    provider = ClaudeInsightProvider()

    response = provider.generate_insights(
        question=question,
        result=result,
    )

    print()
    print("=" * 60)
    print("INSIGHT RESPONSE")
    print("=" * 60)

    print(
        response.model_dump_json(
            indent=2
        )
    )


if __name__ == "__main__":
    main()