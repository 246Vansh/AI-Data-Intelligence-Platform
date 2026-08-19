import os
import json
import re

from dotenv import load_dotenv
from anthropic import Anthropic

from ai.insight_models import InsightResponse
from ai.prompts import INSIGHT_SYSTEM_PROMPT

from time import perf_counter

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
      "type": "trend",
      "title": "Sales increased from March to December",
      "description": "Sales increased between the selected months.",
      "evidence": {
        "rows": [
          {
            "Date": "2010-03-01",
            "sum_Weekly_Sales": 181919802.5
          },
          {
            "Date": "2010-04-01",
            "sum_Weekly_Sales": 231412368.05
          },
          {
            "Date": "2010-12-01",
            "sum_Weekly_Sales": 288760532.72
          }
        ]
      }
    },
    {
      "type": "difference",
      "title": "Large gap between peak and lowest months",
      "description": "There is a large difference between the highest and lowest months.",
      "evidence": null
    }
  ]
},
{
  "type": "coverage",
  "title": "Data coverage is incomplete",
  "description": "Only 4 of the 11 expected monthly periods are present.",
  "evidence": {
    "date_column": "Date",
    "frequency": "month",
    "min_date": "2010-02-01T00:00:00",
    "max_date": "2010-12-01T00:00:00",
    "observed_periods": 4,
    "expected_periods": 11,
    "missing_periods": [
      "2010-05",
      "2010-06",
      "2010-07",
      "2010-08",
      "2010-09",
      "2010-10",
      "2010-11"
    ],
    "is_continuous": false
  }
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
            "the claim can be supported by the supplied result.\n\n"
            + "2. Evidence must be exactly one of:\n\n"
            + "   a) null\n\n"
            + "   b) a single-row evidence object:\n\n"
            + "      {\n"
            + '        "column": "...",\n'
            + '        "value": ...,\n'
            + '        "row": {...}\n'
            + "      }\n\n"
            + "   c) a multi-row evidence object:\n\n"
            + "      {\n"
            + '        "rows": [\n'
            + "          {...},\n"
            + "          {...}\n"
            + "        ]\n"
            + "      }\n\n"
            + "3. Never create partial evidence objects.\n\n"
            + "4. Never use null for column, value, or row inside "
            "a single-row evidence object.\n\n"
            + "5. If a claim depends on multiple observations, "
            "use multi-row evidence.\n\n"
            + "6. Multi-row evidence rows MUST come directly from "
            "the supplied analysis result.\n\n"
            + "7. Do not invent rows.\n\n"
            + "8. Do not modify values.\n\n"
            + "9. Do not round evidence values.\n\n"
            + "10. The evidence must contain only rows that actually "
            "support the insight.\n\n"
            + "11. For a trend, provide at least two rows when the "
            "trend can be established from the supplied result.\n\n"
            + "12. For a comparison involving multiple observations, "
            "provide all relevant comparison rows.\n\n"
            + "13. If an insight cannot be supported by the supplied "
            "result, return:\n\n"
            + '    "evidence": null\n\n'
            + "14. The verified analytical context is authoritative.\n\n"
            + "15. Do not contradict the verified analytical context.\n\n"
            + "16. Do not make claims stronger than the available "
            "evidence supports.\n\n"
            + "17. Do not assume missing dates or missing observations "
            "exist.\n\n" + "18. Date coverage information supplied in the "
            "verified analytical context is authoritative.\n\n"
            + "19. If date_coverage reports missing_periods, "
            "you may state that those periods are missing.\n\n"
            + "20. Do not infer missing periods from only the "
            "visible result rows when date_coverage is available.\n\n"
            + "21. If you make a data coverage claim, use "
            "evidence: null unless the claim is directly "
            "supported by supplied verified context.\n\n"
            + "22. Do not invent dates, periods, or coverage statistics.\n\n"
            + "24. For a coverage insight, evidence MUST be a "
            "CoverageEvidence object.\n\n"
            + "25. Coverage evidence MUST exactly match the "
            "verified date_coverage context.\n\n"
            + "26. Never invent missing periods.\n\n"
            + "27. Never modify observed_periods or expected_periods.\n\n"
            + "28. Never claim continuous data when is_continuous is false.\n\n"
            + "29. Return ONLY valid JSON."
        )

        # -----------------------------------------
        # Call Claude
        # -----------------------------------------

        api_start = perf_counter()

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

        api_time = (perf_counter() - api_start) * 1000
        print("\nAI INSIGHT PERFORMANCE")
        print("----------------------")
        print(f"model: {self.model}")
        print(f"prompt_chars: {len(user_prompt)}")
        print(f"api_request: {api_time:.2f} ms")

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
