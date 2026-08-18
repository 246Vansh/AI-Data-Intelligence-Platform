import os

from dotenv import load_dotenv

from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data
from data_engine.metadata import get_metadata

from ai.planner import create_analysis_plan


load_dotenv()


INPUT_PATH = "data/raw/Walmart_Sales.csv"


def main():

    provider = os.getenv(
        "AI_PROVIDER",
        "not configured",
    )

    print("Loading dataset...")

    df = load_csv(INPUT_PATH)

    df = clean_walmart_data(df)

    print("Generating metadata...")

    metadata = get_metadata(df)

    question = (
        "Show me the top 5 stores by average weekly sales during holidays."
    )

    print()
    print("=" * 60)
    print("AI PROVIDER")
    print("=" * 60)

    print(provider)

    print()
    print("=" * 60)
    print("USER QUESTION")
    print("=" * 60)

    print(question)

    print()
    print("=" * 60)
    print("ASKING AI FOR ANALYSIS PLAN")
    print("=" * 60)

    plan = create_analysis_plan(
        user_question=question,
        metadata=metadata,
    )

    print()
    print("=" * 60)
    print("AI ANALYSIS PLAN")
    print("=" * 60)

    print(
        plan.model_dump_json(
            indent=2
        )
    )


if __name__ == "__main__":
    main()