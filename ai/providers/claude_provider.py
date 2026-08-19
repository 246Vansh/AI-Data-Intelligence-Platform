import os
import json
import re
import time
from dotenv import load_dotenv
from anthropic import Anthropic

from ai.planner_models import AnalysisPlanResponse
from ai.prompts import SYSTEM_PROMPT

load_dotenv()


class ClaudeProvider:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")

        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

        self.model = os.getenv(
            "CLAUDE_MODEL",
            "claude-sonnet-5",
        )

        self.client = Anthropic(api_key=api_key)

    def create_analysis_plan(
        self,
        user_question: str,
        metadata: dict,
    ) -> AnalysisPlanResponse:
        total_start = time.perf_counter()

        # -----------------------------------------
        # Metadata serialization
        # -----------------------------------------
        metadata_text = json.dumps(
            metadata,
            indent=2,
            default=str,
        )

        metadata_end = time.perf_counter()

        # -----------------------------------------
        # Build prompt
        # -----------------------------------------
        user_prompt = f"""Dataset metadata:
        
        {metadata_text}
        
        
        User question:
        
        {user_question}
        
        
        Return ONLY a valid JSON object.
        
        Do not include:
        - Markdown
        - ```json
        - explanations
        - comments
        - introductory text
        
        The JSON must match this structure:
        
        {{
            "status": "success",
            "reason": null,
            "filters": [],
            "group_by": [],
            "metric": "column_name",
            "aggregation": "sum",
            "sort": "desc",
            "limit": 10,
            "visualization": {{
                "type": "bar",
                "title": "chart title"
            }}
        }}
        
        If the requested analysis cannot be performed
        using the supplied dataset metadata, return:
        
        {{
            "status": "invalid",
            "reason": "Explain why the request cannot be performed.",
            "filters": [],
            "group_by": [],
            "metric": null,
            "aggregation": null,
            "sort": "desc",
            "limit": null,
            "visualization": null
        }}
        """

        prompt_end = time.perf_counter()

        # -----------------------------------------
        # Claude API call
        # -----------------------------------------
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        )

        api_end = time.perf_counter()

        # -----------------------------------------
        # Extract text block
        # -----------------------------------------
        text_blocks = []

        for block in response.content:
            if getattr(block, "type", None) == "text":
                text_blocks.append(block.text)

        if not text_blocks:
            raise ValueError("Claude response did not contain a text content block.")

        text = "\n".join(text_blocks).strip()

        # -----------------------------------------
        # Remove Markdown JSON fences
        # -----------------------------------------
        text = re.sub(
            r"^```json\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"^```\s*",
            "",
            text,
        )

        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

        text = text.strip()

        parsing_end = time.perf_counter()

        # -----------------------------------------
        # Parse JSON
        # -----------------------------------------
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(
                r"\{.*\}",
                text,
                re.DOTALL,
            )

            if not match:
                raise ValueError(
                    f"Claude did not return valid JSON.\n\nClaude response:\n{text}"
                )

            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Claude returned invalid JSON.\n\nClaude response:\n{text}"
                ) from exc

        json_end = time.perf_counter()

        # -----------------------------------------
        # Pydantic validation
        # -----------------------------------------
        result = AnalysisPlanResponse.model_validate(data)

        validation_end = time.perf_counter()

        # -----------------------------------------
        # Planner performance profile
        # -----------------------------------------
        print()
        print("-" * 55)
        print("CLAUDE PLANNER PROFILE")
        print("-" * 55)

        print(f"metadata serialization : {(metadata_end - total_start) * 1000:.2f} ms")

        print(f"prompt construction    : {(prompt_end - metadata_end) * 1000:.2f} ms")

        print(f"Claude API call        : {(api_end - prompt_end) * 1000:.2f} ms")

        print(f"response extraction    : {(parsing_end - api_end) * 1000:.2f} ms")

        print(f"JSON parsing           : {(json_end - parsing_end) * 1000:.2f} ms")

        print(f"Pydantic validation    : {(validation_end - json_end) * 1000:.2f} ms")

        print(
            f"TOTAL PROVIDER         : {(validation_end - total_start) * 1000:.2f} ms"
        )

        print("-" * 55)
        print()

        return result
