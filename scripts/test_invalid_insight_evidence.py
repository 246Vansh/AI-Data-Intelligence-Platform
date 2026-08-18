import pandas as pd

from ai.insight_models import (
    Insight,
    InsightResponse,
    MultiRowEvidence,
)

from ai.insight_validator import (
    validate_insights,
)

from data_engine.insight_context import (
    build_insight_context,
)


def main():

    # =========================================
    # Create controlled analysis result
    # =========================================

    result = pd.DataFrame(
        [
            {
                "Date": "2010-03-01",
                "sum_Weekly_Sales": 181919802.5,
            },
            {
                "Date": "2010-04-01",
                "sum_Weekly_Sales": 231412368.05,
            },
            {
                "Date": "2010-12-01",
                "sum_Weekly_Sales": 288760532.72,
            },
        ]
    )

    # =========================================
    # Build verified context
    # =========================================

    context = build_insight_context(
        result=result,
        metric_column="sum_Weekly_Sales",
        group_by=["Date"],
    )

    print("=" * 60)
    print("TESTING INVALID MULTI-ROW EVIDENCE")
    print("=" * 60)

    print("\nVERIFIED CONTEXT:")
    print(context)

    # =========================================
    # Deliberately fake trend
    # =========================================

    fake_insight = Insight(
        type="increasing",
        title="Fake increasing trend",
        description="Sales increased continuously.",
        evidence=MultiRowEvidence(
            rows=[
                {
                    "Date": "2010-12-01",
                    "sum_Weekly_Sales": 288760532.72,
                },
                {
                    "Date": "2010-04-01",
                    "sum_Weekly_Sales": 231412368.05,
                },
                {
                    "Date": "2010-03-01",
                    "sum_Weekly_Sales": 181919802.5,
                },
            ]
        ),
    )

    response = InsightResponse(insights=[fake_insight])

    # =========================================
    # Validate
    # =========================================

    try:
        validate_insights(
            response,
            context,
        )

    except ValueError as exc:
        print("\nEXPECTED FAILURE:")
        print(exc)

        print("\n✓ Validator correctly rejected the invalid trend evidence.")

        return

    raise AssertionError("Validator FAILED to reject invalid trend evidence.")


if __name__ == "__main__":
    main()
