import re
from typing import Any

from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.column_resolver import resolve_column


class FastPlanner:
    """
    Deterministic first-pass planner.

    Responsibilities:
        1. Handle simple, high-confidence questions quickly.
        2. Never guess when the intent is ambiguous.
        3. Return None when AI reasoning is required.
        4. Never raise an error for an understandable user question.
        5. Leave complex/natural-language questions to the AI planner.
    """

    # =====================================================
    # MAIN PLANNER
    # =====================================================

    def create_plan(
        self,
        question: str,
        metadata: dict,
    ) -> AnalysisPlan | None:

        question = (question or "").strip()

        if not question:
            return None

        columns = metadata.get(
            "columns",
            {},
        )

        if not columns:
            return None

        # -------------------------------------------------
        # 1. Extract any simple filters
        # -------------------------------------------------

        filters, working_question = self._detect_filters(
            question,
            columns,
        )

        # -------------------------------------------------
        # 2. Check for genuinely complex unsupported logic
        # -------------------------------------------------

        if self._has_unsupported_conditions(working_question):
            return None

        # -------------------------------------------------
        # 3. Ranking
        # -------------------------------------------------

        ranking = self._detect_ranking(
            working_question,
            columns,
            filters=filters,
        )

        if ranking is not None:
            return ranking

        # -------------------------------------------------
        # 4. Remove dataset column names before detecting
        # natural-language intent.
        # -------------------------------------------------

        question_without_columns = self._remove_column_phrases(
            working_question,
            columns,
        )

        # -------------------------------------------------
        # 5. Time analysis
        # -------------------------------------------------

        time_granularity = self._detect_time_granularity(
            question_without_columns,
        )

        time_column = None

        if time_granularity is not None:
            time_column = self._find_time_column(
                working_question,
                columns,
            )

            # Cannot safely perform time analysis.
            # Let AI decide.
            if time_column is None:
                return None

        # -------------------------------------------------
        # 6. Grouping
        # -------------------------------------------------

        grouping_columns = self._find_grouping_columns(
            working_question,
            columns,
        )

        # More than one grouping dimension requires
        # semantic reasoning.
        if len(grouping_columns) > 1:
            return None

        # -------------------------------------------------
        # Remove grouping columns from metric candidates.
        # -------------------------------------------------

        metric_candidates = {
            column_name: column_info
            for column_name, column_info in columns.items()
            if column_name not in grouping_columns
        }

        # -------------------------------------------------
        # 7. Metric
        # -------------------------------------------------

        metric = self._find_metric(
            working_question,
            metric_candidates,
        )

        # -------------------------------------------------
        # 8. Aggregation
        # -------------------------------------------------

        aggregation = self._detect_aggregation(
            working_question,
        )

        # -------------------------------------------------
        # If metric or aggregation cannot be confidently
        # detected, defer to AI.
        # -------------------------------------------------

        if metric is None:
            return None

        if aggregation is None:
            return None

        # -------------------------------------------------
        # Time-based plan
        # -------------------------------------------------

        if time_column is not None:
            return AnalysisPlan(
                filters=filters,
                group_by=[time_column],
                metric=metric,
                aggregation=aggregation,
                sort="asc",
                sort_by="time",
                visualization="line",
                time_granularity=time_granularity,
                time_column=time_column,
            )

        # -------------------------------------------------
        # Explicit grouped aggregation
        # -------------------------------------------------

        if len(grouping_columns) == 1:
            return AnalysisPlan(
                filters=filters,
                group_by=[grouping_columns[0]],
                metric=metric,
                aggregation=aggregation,
                sort="desc",
                sort_by="metric",
                visualization="bar",
            )

        # -------------------------------------------------
        # Detect explicitly mentioned dimensions.
        # -------------------------------------------------

        question_lower = working_question.lower()

        mentioned_dimensions = [
            column_name
            for column_name, column_info in columns.items()
            if column_name != metric
            and column_info.get("role")
            in {
                "dimension",
                "categorical",
            }
            and self._column_is_explicitly_mentioned(
                column_name,
                question_lower,
            )
        ]

        if len(mentioned_dimensions) > 1:
            return None

        if len(mentioned_dimensions) == 1:
            return AnalysisPlan(
                filters=filters,
                group_by=[mentioned_dimensions[0]],
                metric=metric,
                aggregation=aggregation,
                sort="desc",
                sort_by="metric",
                visualization="bar",
            )

        # -------------------------------------------------
        # Normal aggregation
        # -------------------------------------------------

        return AnalysisPlan(
            filters=filters,
            metric=metric,
            aggregation=aggregation,
            sort="desc",
            sort_by="metric",
            visualization="table",
        )


    # =====================================================
    # COLUMN PHRASE REMOVAL
    # =====================================================

    def _remove_column_phrases(
        self,
        question: str,
        columns: dict[str, Any],
    ) -> str:

        from data_engine.column_resolver import (
            normalize_column_name,
        )

        cleaned = normalize_column_name(question)

        column_phrases = sorted(
            (normalize_column_name(name) for name in columns),
            key=len,
            reverse=True,
        )

        for phrase in column_phrases:
            if not phrase:
                continue

            cleaned = re.sub(
                r"(?<!\w)" + re.escape(phrase) + r"(?!\w)",
                " ",
                cleaned,
            )

        return cleaned

    # =====================================================
    # GROUPING DETECTION
    # =====================================================

    def _find_grouping_columns(
        self,
        question: str,
        columns: dict[str, Any],
    ) -> list[str]:

        from data_engine.column_resolver import (
            normalize_column_name,
        )

        normalized_question = normalize_column_name(question)

        found: list[str] = []

        grouping_patterns = [
            r"\bper\s+",
            r"\bby\s+",
            r"\bfor each\s+",
            r"\beach\s+",
            r"\bacross\s+",
            r"\bin each\s+",
            r"\bgrouped by\s+",
            r"\bgroup by\s+",
            r"\bbased on\s+",
            r"\baccording to\s+",
        ]

        for column_name in columns:
            normalized_column = normalize_column_name(column_name)

            if not normalized_column:
                continue

            for prefix in grouping_patterns:
                pattern = prefix + re.escape(normalized_column) + r"(?!\w)"

                if re.search(
                    pattern,
                    normalized_question,
                ):
                    found.append(column_name)
                    break

        return list(dict.fromkeys(found))

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
    # TIME COLUMN
    # =====================================================

    def _find_time_column(
        self,
        question: str,
        columns: dict[str, Any],
    ) -> str | None:

        time_columns = [
            column_name
            for column_name, column_metadata in columns.items()
            if column_metadata.get("role") == "time"
        ]

        if not time_columns:
            return None

        question_lower = question.lower()

        explicit_matches = [
            column_name
            for column_name in time_columns
            if self._column_is_explicitly_mentioned(
                column_name,
                question_lower,
            )
        ]

        if len(explicit_matches) == 1:
            return explicit_matches[0]

        if len(explicit_matches) > 1:
            return None

        if len(time_columns) == 1:
            return time_columns[0]

        return None

    # =====================================================
    # EXPLICIT COLUMN MATCH
    # =====================================================

    def _column_is_explicitly_mentioned(
        self,
        column_name: str,
        question_lower: str,
    ) -> bool:

        column_lower = column_name.lower()

        if column_lower in question_lower:
            return True

        normalized_column = column_lower.replace(
            "_",
            " ",
        )

        if normalized_column in question_lower:
            return True

        return False

    # =====================================================
    # TIME GRANULARITY
    # =====================================================

    def _detect_time_granularity(
        self,
        question: str,
    ) -> str | None:

        question_lower = question.lower()

        patterns = {
            "day": [
                r"\bdaily\b",
                r"\bper day\b",
                r"\bby day\b",
                r"\beach day\b",
                r"\bday[- ]wise\b",
            ],
            "week": [
                r"\bweekly\b",
                r"\bper week\b",
                r"\bby week\b",
                r"\beach week\b",
                r"\bweek[- ]wise\b",
            ],
            "month": [
                r"\bmonthly\b",
                r"\bper month\b",
                r"\bby month\b",
                r"\beach month\b",
                r"\bmonth[- ]wise\b",
            ],
            "quarter": [
                r"\bquarterly\b",
                r"\bper quarter\b",
                r"\bby quarter\b",
                r"\beach quarter\b",
                r"\bquarter[- ]wise\b",
            ],
            "year": [
                r"\byearly\b",
                r"\bannually\b",
                r"\bper year\b",
                r"\bby year\b",
                r"\beach year\b",
                r"\byear[- ]wise\b",
            ],
        }

        matches = []

        for granularity, expressions in patterns.items():
            for expression in expressions:
                if re.search(
                    expression,
                    question_lower,
                ):
                    matches.append(granularity)
                    break

        if len(matches) != 1:
            return None

        return matches[0]

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
                r"\boverall total\b",
                r"\bcombined\b",
                r"\bin total\b",
            ],
            "mean": [
                r"\baverage\b",
                r"\bavg\b",
                r"\bmean\b",
                r"\btypical\b",
            ],
            "median": [
                r"\bmedian\b",
            ],
            "min": [
                r"\bminimum\b",
                r"\bmin\b",
                r"\blowest\b",
                r"\bsmallest\b",
            ],
            "max": [
                r"\bmaximum\b",
                r"\bmax\b",
                r"\bhighest\b",
                r"\blargest\b",
                r"\bgreatest\b",
            ],
            "count": [
                r"\bcount\b",
                r"\bnumber of\b",
                r"\bhow many\b",
                r"\bhow much\b",
                r"\bquantity of\b",
                r"\bnumber\b",
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

        matches = list(dict.fromkeys(matches))

        if len(matches) != 1:
            return None

        return matches[0]

    # =====================================================
    # TOP / BOTTOM N
    # =====================================================

    def _detect_ranking(
        self,
        question: str,
        columns: dict[str, Any],
        filters: list[FilterCondition] | None = None,
    ) -> AnalysisPlan | None:

        question_lower = question.lower()

        top_match = re.search(
            r"\btop\s+(\d+)\b",
            question_lower,
        )

        bottom_match = re.search(
            r"\bbottom\s+(\d+)\b",
            question_lower,
        )

        if top_match and bottom_match:
            return None

        if not top_match and not bottom_match:
            return None

        if top_match:
            limit = int(top_match.group(1))
            sort = "desc"
        else:
            limit = int(bottom_match.group(1))
            sort = "asc"

        if limit <= 0:
            return None

        entity_column = self._find_ranked_entity(
            question_lower,
            columns,
        )

        metric_candidates = {
            column_name: column_info
            for column_name, column_info in columns.items()
            if column_name != entity_column
        }

        metric = self._find_metric(
            question,
            metric_candidates,
        )

        if metric is None and filters:
            for f in filters:
                if f.column in metric_candidates and metric_candidates[f.column].get("role") == "metric":
                    metric = f.column
                    break

        if metric is None:
            numeric_metrics = [
                c for c, meta in metric_candidates.items()
                if meta.get("role") == "metric"
            ]
            if len(numeric_metrics) == 1:
                metric = numeric_metrics[0]

        if metric is None:
            return None


        if entity_column is None:
            dimensions = [
                column_name
                for column_name, column_metadata in columns.items()
                if column_metadata.get("role")
                in {
                    "dimension",
                    "categorical",
                }
                and column_name != metric
                and self._column_is_explicitly_mentioned(
                    column_name,
                    question_lower,
                )
            ]

            if len(dimensions) != 1:
                return None

            entity_column = dimensions[0]

        aggregation = self._detect_ranking_aggregation(question_lower)

        return AnalysisPlan(
            filters=filters or [],
            group_by=[entity_column],
            metric=metric,
            aggregation=aggregation,
            sort=sort,
            sort_by="metric",
            limit=limit,
            visualization="bar",
        )

    # =====================================================
    # RANKED ENTITY
    # =====================================================

    def _find_ranked_entity(
        self,
        question_lower: str,
        columns: dict[str, Any],
    ) -> str | None:

        from data_engine.column_resolver import (
            normalize_column_name,
        )

        match = re.search(
            r"\b(?:top|bottom)\s+\d+\s+"
            r"([a-z0-9_ \-]+?)"
            r"(?:\s+(?:by|per|based|according|in|for)\b|$)",
            question_lower,
        )

        if not match:
            return None

        phrase = normalize_column_name(match.group(1))

        if not phrase:
            return None

        variants = {phrase}

        if phrase.endswith("ies"):
            variants.add(phrase[:-3] + "y")

        if phrase.endswith("es"):
            variants.add(phrase[:-2])

        if phrase.endswith("s"):
            variants.add(phrase[:-1])

        matches = [
            column_name
            for column_name in columns
            if normalize_column_name(column_name) in variants
        ]

        if len(matches) != 1:
            return None

        return matches[0]

    # =====================================================
    # RANKING AGGREGATION
    # =====================================================

    def _detect_ranking_aggregation(
        self,
        question: str,
    ) -> str:

        question_lower = question.lower()

        if re.search(
            r"\b(average|avg|mean)\b",
            question_lower,
        ):
            return "mean"

        if re.search(
            r"\bmedian\b",
            question_lower,
        ):
            return "median"

        if re.search(
            r"\b(minimum|min|lowest|smallest)\b",
            question_lower,
        ):
            return "min"

        if re.search(
            r"\b(maximum|max|highest|largest|greatest)\b",
            question_lower,
        ):
            return "max"

        return "sum"

    # =====================================================
    # FILTER EXTRACTION
    # =====================================================

    def _detect_filters(
        self,
        question: str,
        columns: dict[str, Any],
    ) -> tuple[list[FilterCondition], str]:
        filters: list[FilterCondition] = []
        cleaned_question = question

        op_map = [
            (r">=", ">="),
            (r"<=", "<="),
            (r"!=", "!="),
            (r"==", "="),
            (r"=", "="),
            (r">", ">"),
            (r"<", "<"),
            (r"\bgreater than or equal to\b", ">="),
            (r"\bat least\b", ">="),
            (r"\bgreater than\b", ">"),
            (r"\bmore than\b", ">"),
            (r"\bhigher than\b", ">"),
            (r"\babove\b", ">"),
            (r"\bless than or equal to\b", "<="),
            (r"\bat most\b", "<="),
            (r"\bless than\b", "<"),
            (r"\bfewer than\b", "<"),
            (r"\blower than\b", "<"),
            (r"\bbelow\b", "<"),
            (r"\bequal to\b", "="),
            (r"\bequals\b", "="),
            (r"\bis\b", "="),
        ]

        for col_name in sorted(columns.keys(), key=len, reverse=True):
            col_normalized = col_name.replace("_", " ")
            col_escaped = re.escape(col_name)
            col_norm_escaped = re.escape(col_normalized)

            for op_pattern, canonical_op in op_map:
                pattern = (
                    rf"(?:\b(?:where|with|having|for)\s+)?\b({col_escaped}|{col_norm_escaped})\b\s*"
                    rf"(?:{op_pattern})\s*"
                    rf"(?:['\"]([^'\"]+)['\"]|([a-zA-Z0-9_.-]+))"
                )

                match = re.search(pattern, cleaned_question, re.IGNORECASE)
                if match:
                    raw_val = match.group(2) if match.group(2) is not None else match.group(3)
                    if raw_val is not None:
                        raw_val = raw_val.strip()
                        val: Any = raw_val
                        try:
                            if "." in raw_val:
                                val = float(raw_val)
                            else:
                                val = int(raw_val)
                        except ValueError:
                            val = raw_val

                        filters.append(
                            FilterCondition(
                                column=col_name,
                                operator=canonical_op,
                                value=val,
                            )
                        )
                        cleaned_question = (
                            cleaned_question[: match.start()]
                            + " "
                            + cleaned_question[match.end() :]
                        )
                        cleaned_question = re.sub(r"\s+", " ", cleaned_question).strip()
                        break

        return filters, cleaned_question

    # =====================================================
    # UNSUPPORTED / COMPLEX CONDITIONS
    # =====================================================

    def _has_unsupported_conditions(
        self,
        question: str,
    ) -> bool:

        question_lower = question.lower()

        unsupported_patterns = [
            r"\bduring\b",
            r"\bwithout\b",
            r"\bbetween\b",
            r"\bafter\b",
            r"\bbefore\b",
            r"\band\b.+\bor\b",
        ]

        return any(
            re.search(
                pattern,
                question_lower,
            )
            for pattern in unsupported_patterns
        )

