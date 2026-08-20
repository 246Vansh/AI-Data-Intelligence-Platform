from ai.insight_providers.claude_insight_provider import (
    ClaudeInsightProvider,
)


def main():

    print("=" * 60)
    print("TESTING CLAUDE INSIGHT PROVIDER")
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

    context = {
        "row_count": 4,
        "metric_column": "sum_Weekly_Sales",
        "group_by": ["Date"],
        "result_rows": result["rows"],
        "highest": {
            "value": 288760532.72,
            "row": {
                "Date": "2010-12-01",
                "sum_Weekly_Sales": 288760532.72,
            },
        },
        "lowest": {
            "value": 181919802.50,
            "row": {
                "Date": "2010-03-01",
                "sum_Weekly_Sales": 181919802.50,
            },
        },
        "difference": 106840730.22,
        "trend": {
            "type": "mixed",
            "direction": "mixed",
            "first_value": 190332983.04,
            "last_value": 288760532.72,
            "change": 98427549.68,
        },
        "date_coverage": {
            "date_column": "Date",
            "frequency": "month",
            "min_date": "2010-02-01T00:00:00",
            "max_date": "2010-12-01T00:00:00",
            "observed_periods": 4,
            "expected_periods": 11,
            "missing_periods": [
                "2010-05",
                "2010-06",
                "2010-07",
                "2010-08",
                "2010-09",
                "2010-10",
                "2010-11",
            ],
            "is_continuous": False,
        },
    }

    print()
    print("QUESTION:")
    print(question)

    print()
    print("GENERATING INSIGHTS...")

    provider = ClaudeInsightProvider()

    response = provider.generate_insights(
        question=question, result=result, context=context
    )

    print()
    print("=" * 60)
    print("INSIGHT RESPONSE")
    print("=" * 60)

    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
