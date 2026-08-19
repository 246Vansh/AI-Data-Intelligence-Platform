import re
from typing import Any

from data_engine.analysis_plan import AnalysisPlan
from data_engine.column_resolver import (
    resolve_column,
)

# =========================================================
# FAST PLANNER
# =========================================================
#
# Handles only highly predictable questions.
#
# Responsibilities:
#   - Detect simple aggregations
#   - Detect top/bottom N rankings
#   - Use dataset metadata to identify valid metrics/dimensions
#   - Produce the same AnalysisPlan used by the AI planner
#
# It does NOT:
#   - execute data
#   - access raw dataset values
#   - bypass validation
#   - contain dataset-specific column names
#   - call an AI model
#
# If the question cannot be safely represented,
# it returns None and the caller should use the AI planner.
# =========================================================


class FastPlanner:
    def create_plan(
        self,
        question: str,
        metadata: dict,
    ) -> AnalysisPlan | None:

        question = question.strip()

        if not question:
            return None

        columns = metadata.get(
            "columns",
            {},
        )

        if not columns:
            return None

        # -------------------------------------------------
        # Fast Planner capability boundary
        #
        # Check this BEFORE ranking/aggregation detection.
        # If the question contains a condition the Fast
        # Planner cannot represent, immediately fallback
        # to the AI planner.
        # -------------------------------------------------

        if self._has_unsupported_conditions(question):
            return None

        # -------------------------------------------------
        # Top / bottom N ranking
        # -------------------------------------------------

        ranking = self._detect_ranking(
            question,
            columns,
        )

        if ranking is not None:
            return ranking

        # -------------------------------------------------
        # Find requested metric
        # -------------------------------------------------

        metric = self._find_metric(
            question,
            columns,
        )

        if metric is None:
            return None

        # -------------------------------------------------
        # Simple aggregation
        # -------------------------------------------------

        aggregation = self._detect_aggregation(
            question,
        )

        if aggregation is None:
            return None

        return AnalysisPlan(
            metric=metric,
            aggregation=aggregation,
            sort="desc",
            sort_by="metric",
            visualization="table",
        )

    # =====================================================
    # METRIC DETECTION
    # =====================================================

    def _find_metric(
        self,
        question: str,
        columns: dict[str, Any],
    ) -> str | None:

        return resolve_column(
            question=question,
            columns=columns,
            allowed_roles={"metric"},
        )

    # =====================================================
    # AGGREGATION DETECTION
    # =====================================================

    def _detect_aggregation(
        self,
        question: str,
    ) -> str | None:

        question_lower = question.lower()

        patterns = {
            "sum": [
                r"\btotal\b",
                r"\bsum\b",
            ],
            "mean": [
                r"\baverage\b",
                r"\bavg\b",
                r"\bmean\b",
            ],
            "median": [
                r"\bmedian\b",
            ],
            "min": [
                r"\bminimum\b",
                r"\bmin\b",
                r"\blowest\b",
            ],
            "max": [
                r"\bmaximum\b",
                r"\bmax\b",
                r"\bhighest\b",
            ],
            "count": [
                r"\bcount\b",
                r"\bnumber of\b",
            ],
        }

        matches = []

        for aggregation, expressions in patterns.items():
            for expression in expressions:
                if re.search(
                    expression,
                    question_lower,
                ):
                    matches.append(aggregation)

                    break

        # -------------------------------------------------
        # Ambiguous aggregation
        # -------------------------------------------------

        if len(set(matches)) != 1:
            return None

        return matches[0]

    # =====================================================
    # TOP / BOTTOM N
    # =====================================================

    def _detect_ranking(
        self,
        question: str,
        columns: dict[str, Any],
    ) -> AnalysisPlan | None:

        question_lower = question.lower()

        # -------------------------------------------------
        # Detect ranking direction
        # -------------------------------------------------

        top_match = re.search(
            r"\btop\s+(\d+)\b",
            question_lower,
        )

        bottom_match = re.search(
            r"\bbottom\s+(\d+)\b",
            question_lower,
        )

        # Cannot safely understand both.
        if top_match and bottom_match:
            return None

        # No ranking.
        if not top_match and not bottom_match:
            return None

        # -------------------------------------------------
        # Determine limit + sort
        # -------------------------------------------------

        if top_match:
            limit = int(top_match.group(1))

            sort = "desc"

        else:
            limit = int(bottom_match.group(1))

            sort = "asc"

        # -------------------------------------------------
        # Find metric
        # -------------------------------------------------

        metric = self._find_metric(
            question,
            columns,
        )

        if metric is None:
            return None

        # -------------------------------------------------
        # Find dimension
        # -------------------------------------------------

        dimensions = []

        for column_name, metadata in columns.items():
            role = metadata.get("role")

            if role not in {
                "dimension",
                "categorical",
            }:
                continue

            column_lower = column_name.lower()

            if column_lower in question_lower:
                dimensions.append(column_name)

        # Ranking must have exactly one dimension.
        if len(dimensions) != 1:
            return None

        # -------------------------------------------------
        # Determine aggregation
        # -------------------------------------------------

        aggregation = self._detect_ranking_aggregation(question_lower)

        # -------------------------------------------------
        # Build AnalysisPlan
        # -------------------------------------------------

        return AnalysisPlan(
            group_by=[dimensions[0]],
            metric=metric,
            aggregation=aggregation,
            sort=sort,
            sort_by="metric",
            limit=limit,
            visualization="bar",
        )

    # =====================================================
    # RANKING AGGREGATION
    # =====================================================

    def _detect_ranking_aggregation(
        self,
        question: str,
    ) -> str:

        if "average" in question or "avg" in question or "mean" in question:
            return "mean"

        if "median" in question:
            return "median"

        if "minimum" in question or "min" in question:
            return "min"

        if "maximum" in question or "max" in question:
            return "max"

        # Ranking without an explicit aggregation
        # defaults to sum.
        return "sum"

    def _has_unsupported_conditions(
        self,
        question: str,
    ) -> bool:

        question_lower = question.lower()

        unsupported_patterns = [
            r"\bduring\b",
            r"\bwhere\b",
            r"\bwhen\b",
            r"\bwith\b",
            r"\bwithout\b",
            r"\bbetween\b",
            r"\bafter\b",
            r"\bbefore\b",
            r"\bgreater than\b",
            r"\bless than\b",
            r"\babove\b",
            r"\bbelow\b",
            r"\bequal to\b",
        ]

        return any(
            re.search(
                pattern,
                question_lower,
            )
            for pattern in unsupported_patterns
        )

    def _has_unsupported_conditions(
        self,
        question: str,
    ) -> bool:

        question_lower = question.lower()

        unsupported_patterns = [
            r"\bduring\b",
            r"\bwhere\b",
            r"\bwhen\b",
            r"\bwith\b",
            r"\bwithout\b",
            r"\bbetween\b",
            r"\bafter\b",
            r"\bbefore\b",
            r"\bgreater than\b",
            r"\bless than\b",
            r"\babove\b",
            r"\bbelow\b",
            r"\bequal to\b",
        ]

        return any(
            re.search(
                pattern,
                question_lower,
            )
            for pattern in unsupported_patterns
        )
