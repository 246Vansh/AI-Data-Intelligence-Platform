from ai.fast_planner import FastPlanner


def main():

    planner = FastPlanner()

    metadata = {
        "columns": {
            "Revenue": {
                "role": "metric",
            },
            "Region": {
                "role": "dimension",
            },
            "Order_Date": {
                "role": "time",
            },
        }
    }

    questions = [
        "Show total revenue",
        "Show average revenue",
        "Show maximum revenue",
        "Show minimum revenue",
        "Show the top 5 regions by revenue",
        "Show the bottom 3 regions by average revenue",
        "Which regions performed unusually well?",
        "Compare revenue during holidays",
    ]

    print("=" * 60)
    print("TESTING FAST PLANNER")
    print("=" * 60)

    for question in questions:
        plan = planner.create_plan(
            question=question,
            metadata=metadata,
        )

        print(
            "\nQUESTION:\n"
            "Show me the top 5 stores by average weekly sales during holidays."
        )

        plan = planner.create_plan(
            question=(
                "Show me the top 5 stores by average weekly sales during holidays."
            ),
            metadata=metadata,
        )

        if plan is None:
            print("\nFAST PLAN:")
            print("→ FALLBACK TO AI")
        else:
            print("\nFAST PLAN:")
            print(plan)


if __name__ == "__main__":
    main()
