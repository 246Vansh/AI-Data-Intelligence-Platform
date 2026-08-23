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

        self.client = Anthropic(api_key=api_key)

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

        user_prompt = textwrap.dedent(
            f"""
            You are the planning layer of a dataset-agnostic
            AI data analysis system.

            Your job is NOT to answer the user's question.

            Your job is to understand the user's analytical
            intent and convert it into a structured analysis
            plan that the Data Engine can execute.

            =================================================
            DATASET METADATA
            =================================================

            {metadata_text}

            =================================================
            USER QUESTION
            =================================================

            {user_question}

            =================================================
            PRIMARY OBJECTIVE
            =================================================

            Users are not required to know how to write
            database queries, pandas operations, aggregation
            names, column names, or formal analytical language.

            The user may ask a question casually, indirectly,
            incompletely, or using natural business language.

            You must interpret the user's intended analysis
            when that intent can be safely derived from the
            dataset metadata.

            Examples of acceptable natural-language requests:

                "show sales by region"

                "which region sold the most"

                "what is the average for each category"

                "give me the highest revenue products"

                "how did sales change over time"

                "I want to see monthly revenue"

                "tell me the typical price"

                "which store performed better"

            Do NOT require the user to use exact technical
            terminology.

            =================================================
            DATASET IS THE SOURCE OF TRUTH
            =================================================

            The dataset metadata is the ONLY source of truth
            for available data.

            You MUST:

                - use only real dataset columns
                - use the exact dataset column names
                - respect column roles
                - respect available data types
                - respect time-column metadata
                - use only operations supported by the
                  analysis plan

            NEVER invent a column.

            NEVER invent a metric.

            NEVER assume a conventional column exists.

            NEVER create a column merely because it would be
            common in a particular type of dataset.

            =================================================
            NATURAL LANGUAGE INTERPRETATION
            =================================================

            The user does not need to explicitly mention the
            exact column name.

            You may interpret common analytical language when
            the mapping is supported by the metadata.

            For example:

                "average"
                    -> mean

                "avg"
                    -> mean

                "total"
                    -> sum

                "highest"
                    -> max

                "lowest"
                    -> min

                "number of"
                    -> count

            The adapter will normalize aggregation aliases,
            so you may use the natural analytical term when
            appropriate.

            However, the metric and dimensions themselves MUST
            ultimately resolve to real dataset columns.

            =================================================
            INTENT INTERPRETATION
            =================================================

            Determine what the user is actually trying to
            analyze.

            Consider:

                - requested metric
                - requested aggregation
                - grouping dimension
                - filters
                - ranking
                - limit
                - time analysis
                - sorting
                - comparison
                - visualization

            Do not require the user to explicitly state all
            of these.

            Infer them when the intended meaning is clear and
            supported by the dataset.

            =================================================
            GROUPING INTERPRETATION
            =================================================

            Natural phrases may indicate grouping.

            Examples:

                "sales by region"
                "sales per store"
                "revenue for every category"
                "average price across products"
                "region wise sales"
                "for each department"

            Map the grouping concept to the appropriate
            REAL dataset column.

            Do not invent a grouping column.

            If multiple possible grouping columns exist and
            the question does not provide enough information
            to safely choose one, return "invalid".

            =================================================
            METRIC INTERPRETATION
            =================================================

            Identify the metric from the available metadata.

            The metric MUST correspond to a real dataset
            column.

            Prefer columns whose metadata role is "metric"
            when such metadata is available.

            Do not invent semantic relationships such as:

                revenue -> sales

            unless the actual dataset column is explicitly
            represented by the metadata and can safely support
            that interpretation.

            =================================================
            AGGREGATION
            =================================================

            Supported analytical aggregations are:

                sum
                mean
                median
                min
                max
                count

            Natural-language equivalents may be interpreted:

                total
                average
                avg
                typical
                median
                highest
                maximum
                lowest
                minimum
                number of
                count

            Choose the aggregation that best represents the
            user's intended request.

            =================================================
            RANKING
            =================================================

            Understand natural ranking requests.

            Examples:

                "top products"

                "best 5 stores"

                "highest revenue categories"

                "bottom 10 regions"

            Interpret:

                top -> descending

                bottom -> ascending

            If a number is explicitly provided, use it as
            "limit".

            If the user asks for a ranking without a number,
            do not invent an arbitrary limit unless the
            surrounding plan requirements clearly require one.

            =================================================
            FILTERS
            =================================================

            Understand natural filtering language.

            Examples:

                "sales for India"

                "products above 100"

                "orders greater than 500"

                "customers from Delhi"

            If the required filter column exists, create the
            appropriate structured filter.

            Use only supported operators:

                =
                !=
                >
                >=
                <
                <=

            =================================================
            TIME ANALYSIS
            =================================================

            Time analysis must be based on the dataset
            metadata.

            First identify columns whose metadata role is
            "time".

            If exactly one time column exists, it may be used
            when the user clearly requests time analysis.

            If multiple time columns exist and the question
            does not identify which one is intended, return
            "invalid".

            NEVER assume a column is a time column merely
            because its name looks like:

                date
                timestamp
                order_date
                created_at

            The metadata is authoritative.

            Supported time granularities:

                day
                week
                month
                quarter
                year

            Natural language examples:

                "daily sales"
                    -> day

                "weekly revenue"
                    -> week

                "monthly sales"
                    -> month

                "quarterly performance"
                    -> quarter

                "annual revenue"
                    -> year

            A time word appearing inside a column name does
            NOT automatically mean time grouping.

            Example:

                Weekly_Sales

            does NOT by itself mean:

                time_granularity = "week"

            Time grouping should only be created when the
            user's intent actually requests temporal grouping.

            For chronological analysis use:

                sort_by = "time"
                sort = "asc"
                visualization.type = "line"

            When time grouping is requested:

                time_column MUST contain the exact dataset
                time column name.

                time_granularity MUST be populated.

                group_by should include the time column when
                required by the downstream representation.

            =================================================
            COMPARISON QUESTIONS
            =================================================

            Users may ask comparison questions naturally.

            Examples:

                "which region performed better"

                "compare sales across stores"

                "which category has the highest average"

            If the comparison can be represented as a grouped
            aggregation using available columns, create that
            plan.

            Do not return a natural-language answer.

            =================================================
            AMBIGUITY
            =================================================

            Do NOT reject a question merely because it is
            casually written.

            First try to understand the intended analytical
            operation.

            Return "invalid" ONLY when the request genuinely
            cannot be converted into a reliable analysis plan.

            Examples of genuine invalid cases:

                - required data does not exist
                - required column does not exist
                - multiple columns are equally plausible and
                  the question provides no way to choose
                - question asks for external information
                - question asks for unsupported computation
                - question is unrelated to the dataset

            Do NOT return invalid merely because:

                - grammar is imperfect
                - the user uses informal language
                - the user does not know the aggregation name
                - the user does not use exact column syntax
                - the user asks conversationally

            =================================================
            UNSUPPORTED / EXTERNAL QUESTIONS
            =================================================

            Return:

                status = "invalid"

            when the user asks for information that cannot be
            derived from this dataset.

            Examples:

                "what is the weather today"

                "who is the president"

                "what will sales be next year"

                "tell me a joke"

                "what is the best laptop"

            Unless the required information is actually
            represented in the dataset, do not answer these
            questions.

            =================================================
            NO HALLUCINATION
            =================================================

            NEVER invent:

                columns
                metrics
                dimensions
                filters
                time columns
                calculated values

            If the required information is unavailable,
            return "invalid".

            =================================================
            DO NOT EXECUTE
            =================================================

            You are ONLY a planning layer.

            Do NOT:

                - calculate values
                - inspect individual dataframe rows
                - execute pandas operations
                - answer the question
                - produce numerical results

            Return only the structured plan.

            =================================================
            SUCCESS RESPONSE
            =================================================

            Return a JSON object with:

                {{
                    "status": "success",
                    "reason": null,
                    "filters": [],
                    "group_by": [],
                    "metric": "exact_dataset_column",
                    "aggregation": "sum",
                    "sort": "desc",
                    "sort_by": "metric",
                    "limit": null,
                    "time_column": null,
                    "time_granularity": null,
                    "visualization": {{
                        "type": "table",
                        "title": null
                    }}
                }}

            IMPORTANT:

            "metric", "group_by", "filters[].column", and
            "time_column" must contain exact dataset column
            names from the supplied metadata.

            =================================================
            INVALID RESPONSE
            =================================================

            When the question genuinely cannot be answered
            from the dataset, return:

                {{
                    "status": "invalid",
                    "reason": "This question cannot be answered using the available dataset.",
                    "filters": [],
                    "group_by": [],
                    "metric": null,
                    "aggregation": null,
                    "sort": "desc",
                    "sort_by": "metric",
                    "limit": null,
                    "time_column": null,
                    "time_granularity": null,
                    "visualization": null
                }}

            =================================================
            OUTPUT REQUIREMENTS
            =================================================

            Return ONLY the JSON object.

            Do NOT return:

                - Markdown
                - ```json
                - explanations
                - comments
                - introductory text
                - natural-language answers
                - analysis outside the JSON object
            """
        )

        prompt_end = time.perf_counter()

        # =================================================
        # 4. CLAUDE API CALL
        # =================================================

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
