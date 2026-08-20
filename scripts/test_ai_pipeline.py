from dataclasses import asdict
import json

from data_engine.loader import load_csv
from data_engine.cleaner import clean_walmart_data
from data_engine.metadata import get_metadata
from data_engine.plan_validator import validate_plan
from data_engine.plan_executor import execute_plan

from ai.planner import create_analysis_plan
from ai.adapter import convert_to_analysis_plan


INPUT_PATH = "data/raw/Walmart_Sales.csv"


def main():

    # =========================================
    # 1. LOAD DATA
    # =========================================

    print("Loading dataset...")

    df = load_csv(INPUT_PATH)

    # =========================================
    # 2. CLEAN DATA
    # =========================================

    print("Cleaning dataset...")

    df = clean_walmart_data(df)

    # =========================================
    # 3. GENERATE METADATA
    # =========================================

    print("Generating metadata...")

    metadata = get_metadata(df)

    # =========================================
    # 4. USER QUESTION
    # =========================================

    question = "Show me monthly sales trends."

    print()
    print("=" * 60)
    print("USER QUESTION")
    print("=" * 60)

    print(question)

    # =========================================
    # 5. AI PLANNER
    # =========================================

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

    # =========================================
    # 6. AI → DATA ENGINE ADAPTER
    # =========================================

    print()
    print("=" * 60)
    print("CONVERTING AI PLAN")
    print("=" * 60)

    analysis_plan = convert_to_analysis_plan(ai_plan)

    print(analysis_plan)

    # =========================================
    # 7. VALIDATE PLAN
    # =========================================

    print()
    print("=" * 60)
    print("VALIDATING PLAN")
    print("=" * 60)

    validate_plan(
        df,
        analysis_plan,
    )

    print("PLAN IS VALID.")

    # =========================================
    # 8. EXECUTE PLAN
    # =========================================

    print()
    print("=" * 60)
    print("EXECUTING PLAN")
    print("=" * 60)

    result = execute_plan(
        df,
        analysis_plan,
    )

    print(result)

    # =========================================
    # 9. COMPLETE
    # =========================================

    print()
    print("=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)

    print("AI → Adapter → Validator → Executor")

    print("SUCCESS")


if __name__ == "__main__":
    main()
