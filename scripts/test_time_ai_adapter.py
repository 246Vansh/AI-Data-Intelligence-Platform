from ai.planner_models import (
    AnalysisPlanResponse,
)

from ai.adapter import (
    convert_to_analysis_plan,
)


def main():

    print("=" * 60)
    print("TESTING AI TIME PLAN → ENGINE PLAN")
    print("=" * 60)

    ai_plan = AnalysisPlanResponse(
        status="success",

        filters=[],

        group_by=[
            "Date"
        ],

        metric="Weekly_Sales",

        aggregation="sum",

        sort="asc",

        limit=None,

        time_granularity="month",

        visualization={
            "type": "line",
            "title": "Monthly Sales Trend",
        },
    )

    print()
    print("AI PLAN:")
    print(
        ai_plan.model_dump_json(
            indent=2
        )
    )

    print()
    print("=" * 60)
    print("CONVERTING PLAN")
    print("=" * 60)

    analysis_plan = (
        convert_to_analysis_plan(
            ai_plan
        )
    )

    print()
    print("ENGINE PLAN:")
    print(
        analysis_plan
    )

    print()
    print("=" * 60)
    print("RESULT")
    print("=" * 60)

    print(
        "Time granularity:",
        analysis_plan.time_granularity,
    )

    if (
        analysis_plan.time_granularity
        == "month"
    ):
        print(
            "AI → Adapter → Engine "
            "time capability: SUCCESS"
        )
    else:
        print(
            "Time capability: FAILED"
        )


if __name__ == "__main__":
    main()