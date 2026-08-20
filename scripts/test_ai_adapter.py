import os

from dataclasses import asdict
import json
from dotenv import load_dotenv

from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data
from data_engine.metadata import get_metadata

from ai.planner import create_analysis_plan
from ai.adapter import convert_to_analysis_plan


INPUT_PATH = "data/raw/Walmart_Sales.csv"


load_dotenv()


def main():

    print("Loading dataset...")

    df = load_csv(INPUT_PATH)

    df = clean_walmart_data(df)

    print("Generating metadata...")

    metadata = get_metadata(df)

    question = "Show me the top 5 stores by total weekly sales."

    print()
    print("=" * 60)
    print("USER QUESTION")
    print("=" * 60)

    print(question)

    print()
    print("=" * 60)
    print("GENERATING AI PLAN")
    print("=" * 60)

    ai_plan = create_analysis_plan(
        user_question=question,
        metadata=metadata,
    )

    print(
        json.dumps(
            asdict(ai_plan),
            indent=2,
            default=str,
        )
    )

    print()
    print("=" * 60)
    print("CONVERTING AI PLAN")
    print("=" * 60)

    analysis_plan = convert_to_analysis_plan(ai_plan)

    print(analysis_plan)

    print()
    print("=" * 60)
    print("ADAPTER TEST")
    print("=" * 60)

    print("AI plan successfully converted.")


if __name__ == "__main__":
    main()
