import os
import json

from dotenv import load_dotenv
from openai import OpenAI

from ai.planner_models import AnalysisPlanResponse
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

        self.client = OpenAI(
            api_key=api_key
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

        if response.output_parsed is None:
            raise ValueError(
                "OpenAI did not return a valid "
                "analysis plan."
            )

        return response.output_parsed