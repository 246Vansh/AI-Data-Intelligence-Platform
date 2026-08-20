import os

from dotenv import load_dotenv

from ai.adapter import convert_to_analysis_plan
from data_engine.analysis_plan import AnalysisPlan


from ai.fast_planner import FastPlanner

from ai.providers.openai_provider import (
    OpenAIProvider,
)

from ai.providers.claude_provider import (
    ClaudeProvider,
)


load_dotenv()


PROVIDERS = {
    "openai": OpenAIProvider,
    "claude": ClaudeProvider,
}


def get_provider():

    provider_name = os.getenv(
        "AI_PROVIDER",
        "openai",
    ).lower()

    provider_class = PROVIDERS.get(provider_name)

    if provider_class is None:
        supported = ", ".join(PROVIDERS.keys())

        raise ValueError(
            f"Unsupported AI provider: "
            f"{provider_name}. "
            f"Supported providers: {supported}"
        )

    return provider_class()


def create_analysis_plan(
    user_question: str,
    metadata: dict,
) -> AnalysisPlan:

    # =====================================================
    # 1. FAST DETERMINISTIC PLANNER
    # =====================================================

    fast_planner = FastPlanner()

    fast_plan = fast_planner.create_plan(
        question=user_question,
        metadata=metadata,
    )

    if fast_plan is not None:
        return fast_plan

    # =====================================================
    # 2. AI FALLBACK
    # =====================================================

    provider = get_provider()

    ai_plan = provider.create_analysis_plan(
        user_question=user_question,
        metadata=metadata,
    )

    # =====================================================
    # 3. INVALID AI PLAN
    # =====================================================

    if ai_plan.status == "invalid":
        reason = ai_plan.reason or "The AI could not create a valid analysis plan."

        raise ValueError(f"Invalid analysis request: {reason}")

    # =====================================================
    # 4. AI PLAN → COMMON DATA ENGINE PLAN
    # =====================================================

    return convert_to_analysis_plan(ai_plan)
