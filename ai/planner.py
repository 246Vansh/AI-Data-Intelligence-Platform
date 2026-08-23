import os

from dotenv import load_dotenv

from ai.adapter import convert_to_analysis_plan
from data_engine.analysis_plan import AnalysisPlan

load_dotenv()


def get_provider():
    provider_name = os.getenv(
        "AI_PROVIDER",
        "openai",
    ).lower()

    if provider_name == "openai":
        try:
            from ai.providers.openai_provider import OpenAIProvider

            return OpenAIProvider()
        except ImportError as exc:
            raise RuntimeError(
                "OpenAI provider requires the 'openai' package. "
                "Install it with 'pip install openai'."
            ) from exc

    elif provider_name == "claude":
        try:
            from ai.providers.claude_provider import ClaudeProvider

            return ClaudeProvider()
        except ImportError as exc:
            raise RuntimeError(
                "Claude provider requires the 'anthropic' package. "
                "Install it with 'pip install anthropic'."
            ) from exc

    else:
        raise ValueError(
            f"Unsupported AI provider: {provider_name}. "
            f"Supported providers: openai, claude"
        )


def create_analysis_plan(
    user_question: str,
    metadata: dict,
) -> AnalysisPlan:
    # =====================================================
    # 1. AI PLAN GENERATION
    # =====================================================

    provider = get_provider()

    ai_plan = provider.create_analysis_plan(
        user_question=user_question,
        metadata=metadata,
    )

    # =====================================================
    # 2. INVALID AI PLAN
    # =====================================================

    if ai_plan.status == "invalid":
        reason = ai_plan.reason or "The AI could not create a valid analysis plan."
        raise ValueError(f"Invalid analysis request: {reason}")

    # =====================================================
    # 3. AI PLAN → COMMON DATA ENGINE PLAN
    # =====================================================

    return convert_to_analysis_plan(ai_plan)
