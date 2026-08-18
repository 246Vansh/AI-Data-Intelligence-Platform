from ai.insight_models import (
    Insight,
    InsightResponse,
)

from ai.insight_validator import (
    validate_insights,
)


def main():

    print("=" * 60)
    print("TESTING INSIGHT VALIDATOR")
    print("=" * 60)

    response = InsightResponse(
        insights=[
            Insight(
                type="highest",
                title="Highest sales",
                description=("December recorded the highest sales."),
            ),
            Insight(
                type="lowest",
                title="Lowest sales",
                description=("March recorded the lowest sales."),
            ),
        ]
    )

    print()
    print("VALIDATING INSIGHTS...")

    try:
        validate_insights(response)

        print()
        print("INSIGHTS ARE VALID.")

    except ValueError as exc:
        print()
        print(f"VALIDATION FAILED: {exc}")


if __name__ == "__main__":
    main()
