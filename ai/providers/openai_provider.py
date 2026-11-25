import os
import json

from dotenv import load_dotenv
from openai import APITimeoutError, OpenAI

from ai.planner_models import AnalysisPlanResponse, PlannerTimeoutError
from ai.providers.client_settings import read_max_retries, read_request_timeout
from ai.prompts import SYSTEM_PROMPT


load_dotenv()


class OpenAIProvider:

    def __init__(self):

        api_key = os.getenv(
            "OPENAI_API_KEY"
        )

        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured."
            )

        # Every route in this app is a sync `def`, so they all run
        # on a shared, size-limited thread pool. The SDK's default
        # timeout (600s, x up to 3 attempts with retries) can hold a
        # thread hostage long enough that the pool fills up and even
        # unrelated requests (e.g. GET /) stop getting served at
        # all. Bound it to something sane instead.
        # R4: validated, with retries explicit (see client_settings).
        self.client = OpenAI(
            api_key=api_key,
            timeout=read_request_timeout(),
            max_retries=read_max_retries(),
        )

    def create_analysis_plan(
        self,
        user_question: str,
        metadata: dict,
    ) -> AnalysisPlanResponse:

        metadata_text = json.dumps(
            metadata,
            indent=2,
            default=str,
        )

        user_prompt = f"""
Dataset metadata:

{metadata_text}


User question:

{user_question}
"""

        try:
            response = self.client.responses.parse(
                model="gpt-5.6",
                input=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                text_format=AnalysisPlanResponse,
            )
        except APITimeoutError as exc:
            # R4: after the SDK's own retries - see client_settings.
            raise PlannerTimeoutError("The AI planner request timed out.") from exc

        if response.output_parsed is None:
            raise ValueError(
                "OpenAI did not return a valid "
                "analysis plan."
            )

        return response.output_parsed