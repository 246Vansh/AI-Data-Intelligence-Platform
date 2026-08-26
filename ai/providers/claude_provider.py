import os
import json
import re
import time
import textwrap

from dotenv import load_dotenv
from anthropic import Anthropic

from ai.planner_models import AnalysisPlanResponse
from ai.prompts import SYSTEM_PROMPT


load_dotenv()


# =========================================================
# CLAUDE PROVIDER
# =========================================================


class ClaudeProvider:
    """
    Claude-backed analysis planner.

    Responsibilities:

        1. Receive the user's natural-language question.
        2. Receive dataset metadata.
        3. Understand the user's analytical intent.
        4. Map that intent to REAL dataset columns.
        5. Produce a structured AnalysisPlanResponse.
        6. Never execute the analysis.

    The provider does NOT:
        - calculate results
        - manipulate the dataframe
        - invent columns
        - answer the user's question directly

    The returned AI plan is later normalized by adapter.py
    and validated by plan_validator.py.
    """

    def __init__(self):

        # =================================================
        # API KEY
        # =================================================

        api_key = os.getenv("ANTHROPIC_API_KEY")

        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

        # =================================================
        # MODEL
        # =================================================

        self.model = os.getenv(
            "CLAUDE_MODEL",
            "claude-sonnet-4-6",
        )

        # =================================================
        # OPTIONAL PERFORMANCE PROFILE
        # =================================================

        self.profile_enabled = (
            os.getenv(
                "PLANNER_PROFILE",
                "false",
            ).lower()
            == "true"
        )

        # =================================================
        # CLIENT
        # =================================================

        # Every route in this app is a sync `def`, so they all run
        # on a shared, size-limited thread pool. The SDK's default
        # timeout (read=600s, x up to 3 attempts with retries) can
        # hold a thread hostage long enough that the pool fills up
        # and even unrelated requests (e.g. GET /) stop getting
        # served at all. Bound it to something sane instead.
        request_timeout = float(
            os.getenv(
                "AI_REQUEST_TIMEOUT_SECONDS",
                "60",
            )
        )

        self.client = Anthropic(
            api_key=api_key,
            timeout=request_timeout,
        )

    # =====================================================
    # CREATE ANALYSIS PLAN
    # =====================================================

    def create_analysis_plan(
        self,
        user_question: str,
        metadata: dict,
    ) -> AnalysisPlanResponse:

        total_start = time.perf_counter()

        # =================================================
        # 1. BASIC INPUT VALIDATION
        # =================================================

        if not isinstance(
            user_question,
            str,
        ):
            raise ValueError("User question must be a string.")

        user_question = user_question.strip()

        if not user_question:
            raise ValueError("User question cannot be empty.")

        if not isinstance(
            metadata,
            dict,
        ):
            raise ValueError("Dataset metadata must be a dictionary.")

        # =================================================
        # 2. METADATA SERIALIZATION
        # =================================================

        metadata_text = json.dumps(
            metadata,
            indent=2,
            default=str,
        )

        metadata_end = time.perf_counter()

        # =================================================
        # 3. BUILD PLANNING PROMPT
        # =================================================
        #
        # All stable reasoning rules live only in SYSTEM_PROMPT
        # (ai/prompts.py). This block is just the per-request
        # data: dataset metadata (static per uploaded dataset,
        # its own cache breakpoint below) + the user's question
        # (changes every call).
        # =================================================

        metadata_block = textwrap.dedent(
            f"""
            =================================================
            DATASET METADATA
            =================================================

            {metadata_text}
            """
        )

        question_block = textwrap.dedent(
            f"""
            =================================================
            USER QUESTION
            =================================================

            {user_question}
            """
        )

        prompt_end = time.perf_counter()

        # =================================================
        # 4. CLAUDE API CALL
        # =================================================
        #
        # Two ephemeral cache breakpoints:
        #   1. The system prompt - 100% static across all requests.
        #   2. The metadata block - static per uploaded dataset,
        #      changes only on a new upload.
        # The question block is never cached; it changes per call.
        # =================================================

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": metadata_block,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {
                            "type": "text",
                            "text": question_block,
                        },
                    ],
                }
            ],
        )

        api_end = time.perf_counter()

        # =================================================
        # 5. EXTRACT TEXT BLOCKS
        # =================================================

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

        # =================================================
        # 6. CLEAN JSON RESPONSE
        # =================================================

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

        # =================================================
        # 7. PARSE JSON
        # =================================================

        try:
            data = json.loads(text)

        except json.JSONDecodeError:
            # -------------------------------------------------
            # Fallback extraction.
            #
            # This handles cases where Claude accidentally
            # adds a small amount of text around the JSON.
            # -------------------------------------------------

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

        # =================================================
        # 8. PYDANTIC VALIDATION
        # =================================================

        try:
            result = AnalysisPlanResponse.model_validate(data)

        except Exception as exc:
            raise ValueError(
                "Claude returned a plan that does not "
                "match the expected planner schema.\n\n"
                f"Claude response:\n{text}"
            ) from exc

        validation_end = time.perf_counter()

        # =================================================
        # 9. BASIC RESPONSE SANITY CHECK
        # =================================================
        #
        # Pydantic validates the structure.
        #
        # These checks validate basic semantic consistency
        # before the plan reaches the adapter.
        # =================================================

        if result.status == "success":
            if not result.metric:
                raise ValueError("Claude returned a successful plan without a metric.")

            # -------------------------------------------------
            # Time analysis consistency.
            # -------------------------------------------------

            if result.time_granularity is not None:
                if not result.time_column:
                    raise ValueError(
                        "Claude returned time_granularity without time_column."
                    )

        elif result.status == "invalid":
            # -------------------------------------------------
            # Invalid plans should not contain an executable
            # metric.
            # -------------------------------------------------

            result.metric = None

            result.group_by = []

            result.filters = []

            result.aggregation = None

            result.limit = None

            result.time_column = None

            result.time_granularity = None

            result.visualization = None

        # =================================================
        # 10. OPTIONAL PERFORMANCE PROFILE
        # =================================================

        if self.profile_enabled:
            print()
            print("-" * 60)
            print("CLAUDE PLANNER PROFILE")
            print("-" * 60)

            print(
                f"metadata serialization : {(metadata_end - total_start) * 1000:.2f} ms"
            )

            print(
                f"prompt construction    : {(prompt_end - metadata_end) * 1000:.2f} ms"
            )

            print(f"Claude API call        : {(api_end - prompt_end) * 1000:.2f} ms")

            print(f"response extraction    : {(parsing_end - api_end) * 1000:.2f} ms")

            print(f"JSON parsing           : {(json_end - parsing_end) * 1000:.2f} ms")

            print(
                f"Pydantic validation    : {(validation_end - json_end) * 1000:.2f} ms"
            )

            print(
                "TOTAL PROVIDER         : "
                f"{(validation_end - total_start) * 1000:.2f} ms"
            )

            print("-" * 60)
            print()

        # =================================================
        # 11. RETURN STRUCTURED PLAN
        # =================================================

        return result
