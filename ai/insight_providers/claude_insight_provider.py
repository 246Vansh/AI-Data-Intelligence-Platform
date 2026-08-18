import os
import json
import re

from dotenv import load_dotenv
from anthropic import Anthropic

from ai.insight_models import InsightResponse
from ai.prompts import INSIGHT_SYSTEM_PROMPT


load_dotenv()


class ClaudeInsightProvider:
    def __init__(self):

        api_key = os.getenv("ANTHROPIC_API_KEY")

        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

        self.model = os.getenv(
            "CLAUDE_MODEL",
            "claude-sonnet-5",
        )

        self.client = Anthropic(api_key=api_key)

    def generate_insights(
        self,
        question: str,
        result: dict,
        context: dict,
    ) -> InsightResponse:

        context_text = json.dumps(
            context,
            indent=2,
            default=str,
        )

        result_text = json.dumps(
            result,
            indent=2,
            default=str,
        )

        # -----------------------------------------
        # JSON response example
        # -----------------------------------------

        example_json = """
{
  "insights": [
    {
      "type": "highest",
      "title": "December 2010 records peak sales",
      "description": "December 2010 had the highest monthly sales.",
      "evidence": {
        "column": "sum_Weekly_Sales",
        "value": 288760532.72,
        "row": {
          "Date": "2010-12-01",
          "sum_Weekly_Sales": 288760532.72
        }
      }
    },
    {
      "type": "difference",
      "title": "Large gap between peak and lowest months",
      "description": "The difference between the highest and lowest months is substantial.",
      "evidence": null
    }
  ]
}
"""

        # -----------------------------------------
        # Build prompt
        # -----------------------------------------

        user_prompt = (
            "Original analysis question:\n\n"
            + question
            + "\n\n\n"
            + "Computed analysis result:\n\n"
            + result_text
            + "\n\n\n"
            + "Verified analytical context:\n\n"
            + context_text
            + "\n\n\n"
            + "Return ONLY a valid JSON object.\n\n"
            + "Do not include:\n"
            + "- Markdown\n"
            + "- ```json\n"
            + "- explanations outside the JSON\n"
            + "- comments\n"
            + "- introductory text\n\n"
            + "The JSON must match this structure:\n\n"
            + example_json
            + "\n\n"
            + "EVIDENCE RULES:\n\n"
            + "1. Every factual insight must include evidence when "
            "the claim can be tied to a specific result row.\n\n"
            + "2. Evidence must be either:\n"
            + "   a) null\n"
            + "   OR\n"
            + "   b) a complete evidence object containing:\n"
            + "      - column\n"
            + "      - value\n"
            + "      - row\n\n"
            + "3. NEVER return an evidence object with a null value.\n\n"
            + "4. NEVER return an evidence object with a null row "
            "when the evidence is supposed to identify a specific "
            "result row.\n\n" + "5. If the insight cannot be supported by a single "
            "result row, return:\n\n"
            + '   "evidence": null\n\n'
            + "6. The evidence column must be an exact column from "
            "the supplied analysis result.\n\n"
            + "7. The evidence value must come from the supplied result.\n\n"
            + "8. The evidence row must come from the supplied result.\n\n"
            + "9. Never invent evidence.\n\n"
            + "10. Never modify a value from the supplied result.\n\n"
            + "11. The verified analytical context is authoritative.\n\n"
            + "12. Do not contradict the verified analytical context.\n\n"
            + "13. Do not create partial evidence objects.\n\n"
            + "14. Use evidence null when row-level evidence is not "
            "available or appropriate.\n\n"
            + "15. Do not make claims stronger than the available "
            "evidence supports.\n\n"
            + "16. Use the actual computed result when describing "
            "values, dates, rankings, differences, and trends.\n\n"
            + "17. Do not assume that missing dates or incomplete "
            "time periods exist in the dataset.\n\n" + "Return ONLY valid JSON."
        )

        # -----------------------------------------
        # Call Claude
        # -----------------------------------------

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=INSIGHT_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
        )

        # -----------------------------------------
        # Extract text blocks
        # -----------------------------------------

        text_blocks = []

        for block in response.content:
            if (
                getattr(
                    block,
                    "type",
                    None,
                )
                == "text"
            ):
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
                    "Claude did not return valid "
                    "JSON for insights.\n\n"
                    f"Claude response:\n{text}"
                )

            try:
                data = json.loads(match.group(0))

            except json.JSONDecodeError as exc:
                raise ValueError(
                    "Claude returned invalid "
                    "JSON for insights.\n\n"
                    f"Claude response:\n{text}"
                ) from exc

        # -----------------------------------------
        # Validate insight schema
        # -----------------------------------------

        return InsightResponse.model_validate(data)
