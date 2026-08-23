import os

from dotenv import load_dotenv

from ai.insight_models import (
    InsightResponse,
)

from ai.insight_providers.claude_insight_provider import (
    ClaudeInsightProvider,
)


load_dotenv()


INSIGHT_PROVIDERS = {
    "claude": ClaudeInsightProvider,
}


def get_insight_provider():

    # INSIGHT_PROVIDER is intentionally separate from
    # AI_PROVIDER (which selects the planner). The default
    # must be a key that actually exists in
    # INSIGHT_PROVIDERS, otherwise this function can never
    # succeed without an env override.
    provider_name = os.getenv(
        "INSIGHT_PROVIDER",
        "claude",
    ).lower()

    provider_class = INSIGHT_PROVIDERS.get(provider_name)

    if provider_class is None:
        supported = ", ".join(INSIGHT_PROVIDERS.keys())

        raise ValueError(
            f"Unsupported insight provider: "
            f"{provider_name}. "
            f"Supported providers: {supported}"
        )

    return provider_class()


def generate_insights(
    question: str,
    result: dict,
    context: dict,
) -> InsightResponse:

    provider = get_insight_provider()

    return provider.generate_insights(
        question=question,
        result=result,
        context=context,
    )
