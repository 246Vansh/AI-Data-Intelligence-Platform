import os

from dotenv import load_dotenv

from ai.planner_models import AnalysisPlanResponse

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

    provider_class = PROVIDERS.get(
        provider_name
    )

    if provider_class is None:

        supported = ", ".join(
            PROVIDERS.keys()
        )

        raise ValueError(
            f"Unsupported AI provider: "
            f"{provider_name}. "
            f"Supported providers: {supported}"
        )

    return provider_class()


def create_analysis_plan(
    user_question: str,
    metadata: dict,
) -> AnalysisPlanResponse:

    provider = get_provider()

    return provider.create_analysis_plan(
        user_question=user_question,
        metadata=metadata,
    )