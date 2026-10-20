"""
Bounded follow-up interpretation for /api/analyze (Step 96).

Applies ONE narrow, explicit edit to the most recent successful plan:

- ranking: "make it the bottom 10 instead", "top 3"
  -> sort direction + limit (sort_by metric);
- grouping: "break that down by region" (adds a column),
  "by city instead" (replaces the grouping);
- filters (Step 97), ANDed after the existing ones:
  "only include the North region" (equality on a string dimension;
  the value must match a sampled value, or be quoted verbatim),
  "only include quantity greater than 10" (>, >=, <, <= on a numeric
  column), "use South instead of North" (replaces one existing
  equality filter - the only way a filter is ever replaced).

Everything else returns None. Deterministic and offline: no LLM, no
conversation transcript. The previous plan reaching here was already
re-validated against the requested dataset, and the plan this returns
still goes through the route's canonical validate_plan().

Text left over after the recognized pattern must be filler words, so a
message that says anything more ("top 5 cities in 2023", "break that
down by region and month") is not half-applied - the caller falls back
to a fresh plan or asks for a complete question instead.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any

from data_engine.analysis_plan import AnalysisPlan, FilterCondition
from data_engine.column_resolver import normalize_column_name, resolve_column


# Words that carry no analytical meaning in a short follow-up.
_FILLER = frozenset(
    {
        "a", "an", "and", "can", "change", "do", "give", "instead", "it",
        "just", "let", "lets", "make", "me", "now", "only", "please",
        "rather", "results", "see", "show", "switch", "that", "the", "them",
        "then", "these", "this", "those", "to", "you",
    }
)

# Verbs that say a grouping column is being ADDED to the current one.
_ADD_VERBS = frozenset({"break", "split", "down", "also", "add"})

_RANKING = re.compile(r"\b(top|bottom)\s+(\d+)\b")
_BY_COLUMN = re.compile(r"\bby\s+(?P<column>.+?)(?:\s+instead)?$")

# A filter follow-up must open with one of these cues; the rest of the
# message must then parse completely as one filter.
_FILTER_CUE = re.compile(
    r"^(?:now\s+|and\s+|also\s+)?(?:"
    r"only\s+(?:include|show|keep|use|count)"
    r"|(?:keep|show|include)\s+only"
    r"|filter\s+(?:(?:it|that|this)\s+)?(?:to|by|on|for)"
    r"|(?:limit|restrict)\s+(?:it|that|this)\s+to"
    r")\b"
)

# Explicit references back to the previous analysis. Deliberately
# narrow: a pronoun alone ("orders that shipped") is not a reference.
_REFERENCE = re.compile(
    r"\binstead\b"
    r"|\b(?:break|split)\s+(?:it|that|this|these|those|them)\s+down\b"
    r"|\b(?:what|how)\s+about\b"
    r"|^(?:now\s+|and\s+|also\s+)?"
    r"(?:make|change|switch|turn|sort|show|do|keep|limit)\s+(?:it|that|this|them)\b"
    r"|\b(?:same|previous|last)\s+(?:analysis|result|results|question|chart|query)\b"
    # Filter edits (supported or not) so an unresolvable one is refused
    # rather than planned without its context.
    r"|" + _FILTER_CUE.pattern
    + r"|^(?:now\s+|and\s+|also\s+)?exclude\b"
)

# Comparison phrases -> operators. Only >, >=, <, <=: for these both
# execution engines drop NULLs (SQL NULL comparison / NaN compares
# False), unlike "!=" where they differ. Longest phrases first.
_COMPARISONS = [
    ("greater than or equal to", ">="),
    ("less than or equal to", "<="),
    ("greater than", ">"),
    ("more than", ">"),
    ("less than", "<"),
    ("fewer than", "<"),
    ("at least", ">="),
    ("at most", "<="),
    ("above", ">"),
    ("over", ">"),
    ("below", "<"),
    ("under", "<"),
    (">=", ">="),
    ("<=", "<="),
    (">", ">"),
    ("<", "<"),
]

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_QUOTED = re.compile(r"\"([^\"]{1,200})\"|'([^']{1,200})'")
_QUOTE_TOKEN = "qvalueq"

# Max filters a follow-up may produce - the request contract's bound.
_MAX_FILTERS = 20


@dataclass(frozen=True)
class FollowUp:
    plan: AnalysisPlan
    # Plain-language description of the single edit applied.
    change: str


def references_previous(question: str) -> bool:
    return bool(_REFERENCE.search(_normalize(question)))


def resolve_follow_up(
    question: str,
    previous: AnalysisPlan,
    metadata: dict,
) -> FollowUp | None:
    text = _normalize(question)

    if not text:
        return None

    columns = metadata.get("columns") or {}
    candidates = [
        edit
        for edit in (
            _resolve_ranking(text, previous),
            _resolve_grouping(text, previous, columns),
            _resolve_filter(question, previous, columns),
        )
        if edit is not None
    ]

    # One edit per follow-up; two matches means the message says more
    # than any single edit covers.
    return candidates[0] if len(candidates) == 1 else None


# =========================================================
# Ranking: "bottom 10 instead"
# =========================================================


def _resolve_ranking(text: str, previous: AnalysisPlan) -> FollowUp | None:
    matches = list(_RANKING.finditer(text))

    if len(matches) != 1:
        return None

    match = matches[0]
    rest = text[: match.start()] + " " + text[match.end() :]

    if not _only_filler(rest):
        return None

    # Ranking needs groups to rank.
    if not previous.group_by:
        return None

    direction, count = match.group(1), int(match.group(2))

    if count <= 0:
        return None

    plan = _copy(
        previous,
        sort="desc" if direction == "top" else "asc",
        sort_by="metric",
        limit=count,
    )

    return FollowUp(plan=plan, change=f"changed to the {direction} {count:,} groups")


# =========================================================
# Grouping: "break that down by region" / "by city instead"
# =========================================================


def _resolve_grouping(
    text: str,
    previous: AnalysisPlan,
    columns: dict[str, Any],
) -> FollowUp | None:
    match = _BY_COLUMN.search(text)

    if match is None or text.count(" by ") + text.startswith("by ") != 1:
        return None

    prefix_words = _words(text[: match.start()])

    if any(word not in _FILLER and word not in _ADD_VERBS for word in prefix_words):
        return None

    replace_grouping = "instead" in _words(text)
    add_grouping = bool(_ADD_VERBS & set(prefix_words))

    if replace_grouping == add_grouping:
        # Neither, or contradictory ("break that down by x instead").
        return None

    column_phrase = match.group("column").strip()
    column = resolve_column(
        column_phrase,
        columns,
        allowed_roles={"dimension", "time"},
    )

    # The whole phrase must name the column - "region and month" or
    # "region in 2023" resolve to a column but say more than that.
    if column is None or not _names_column(column_phrase, column):
        return None

    if add_grouping:
        if column in previous.group_by:
            return None

        # "top 5 products" + "by region" would silently become the top 5
        # product/region combinations - ambiguous, so not applied.
        if previous.limit is not None:
            return None

        plan = _copy(previous, group_by=[*previous.group_by, column])

        return FollowUp(plan=plan, change=f"added {column} to the grouping")

    if previous.group_by == [column]:
        return None

    keeps_time = previous.time_column == column
    plan = _copy(
        previous,
        group_by=[column],
        time_column=previous.time_column if keeps_time else None,
        time_granularity=previous.time_granularity if keeps_time else None,
        sort_by=previous.sort_by if keeps_time else "metric",
    )
    before = ", ".join(previous.group_by) or "no grouping"

    return FollowUp(plan=plan, change=f"grouped by {column} instead of {before}")


# =========================================================
# Filters: "only include the North region",
#          "only include quantity greater than 10",
#          "use South instead of North"
# =========================================================

_REPLACE = re.compile(
    r"^(?:now\s+)?(?:(?:use|show|switch\s+to|change\s+(?:it\s+)?to)\s+)?"
    r"(?P<new>.+?)\s+instead\s+of\s+(?P<old>.+)$"
)


def _resolve_filter(
    question: str,
    previous: AnalysisPlan,
    columns: dict[str, Any],
) -> FollowUp | None:
    # At most one quoted value, kept verbatim (its exact spelling is the
    # user's explicit choice); everything else is matched case-insensitively.
    quoted = _QUOTED.findall(question or "")

    if len(quoted) > 1:
        return None

    literal = (quoted[0][0] or quoted[0][1]) if quoted else None
    text = _normalize(_QUOTED.sub(f" {_QUOTE_TOKEN} ", question or "", count=1))

    replace_match = _REPLACE.match(text)

    if replace_match is not None:
        return _replace_equality(
            replace_match.group("new"),
            replace_match.group("old"),
            literal,
            previous,
            columns,
        )

    cue = _FILTER_CUE.match(text)

    if cue is None:
        return None

    body = text[cue.end() :].strip()
    body = re.sub(r"^(?:the\s+)?(?:rows\s+)?(?:(?:where|with)\s+)?", "", body)
    body = re.sub(r"\s+only$", "", body).strip()

    parsed = [
        condition
        for condition in (
            _parse_comparison(body, columns),
            _parse_equality(body, literal, columns),
        )
        if condition is not None
    ]

    if len(parsed) != 1:
        return None

    condition = parsed[0]

    if len(previous.filters) >= _MAX_FILTERS:
        return None

    for existing in previous.filters:
        if existing.column != condition.column:
            continue

        # A second value for the same column would mean OR (or an empty
        # result); a repeated comparison is ambiguous. Replacement must
        # be asked for explicitly ("use X instead of Y").
        if condition.operator == "=" or existing.operator == condition.operator:
            return None

    plan = _copy(previous)
    plan.filters.append(condition)

    return FollowUp(plan=plan, change=f"added the filter {_describe(condition)}")


def _parse_comparison(body: str, columns: dict[str, Any]) -> FilterCondition | None:
    operators = "|".join(re.escape(phrase) for phrase, _ in _COMPARISONS)
    match = re.fullmatch(
        rf"(?P<column>.+?)\s+(?:is\s+)?(?P<op>{operators})\s*(?P<number>{_NUMBER.pattern})",
        body,
    )

    if match is None:
        return None

    numeric_columns = [
        name
        for name, info in columns.items()
        if info.get("data_type") in {"integer", "float"}
        and _names_column(match.group("column"), name)
    ]

    if len(numeric_columns) != 1:
        return None

    operator = dict(_COMPARISONS)[match.group("op")]
    raw = match.group("number")
    value: int | float = float(raw) if "." in raw else int(raw)

    return FilterCondition(numeric_columns[0], operator, value)


def _parse_equality(
    body: str,
    literal: str | None,
    columns: dict[str, Any],
) -> FilterCondition | None:
    body = re.sub(r"^the\s+", "", body)
    matches = []

    for name in _string_dimensions(columns):
        column_phrase = normalize_column_name(name)
        normalized_body = normalize_column_name(body)

        if normalized_body.startswith(column_phrase + " "):
            rest = normalized_body[len(column_phrase) :]
            rest = re.sub(r"^\s*(?:is|equals|equal to|of)\s+", " ", rest)
        elif normalized_body.endswith(" " + column_phrase):
            rest = normalized_body[: -len(column_phrase)]
        else:
            continue

        value = _resolve_value(rest, literal, name, columns)

        if value is not None:
            matches.append(FilterCondition(name, "=", value))

    return matches[0] if len(matches) == 1 else None


def _replace_equality(
    new_phrase: str,
    old_phrase: str,
    literal: str | None,
    previous: AnalysisPlan,
    columns: dict[str, Any],
) -> FollowUp | None:
    old = _strip_column_phrases(old_phrase, columns)
    targets = [
        index
        for index, existing in enumerate(previous.filters)
        if existing.operator == "="
        and isinstance(existing.value, str)
        and (
            normalize_column_name(existing.value) == old
            or (old == _QUOTE_TOKEN and existing.value == literal)
        )
    ]

    if len(targets) != 1:
        return None

    index = targets[0]
    column = previous.filters[index].column

    # "use South instead of North region code" names region_code: never
    # replace a filter on a different column than the one named.
    named = _named_columns(old_phrase, columns)

    if named and column not in named:
        return None
    value = _resolve_value(new_phrase, literal, column, columns)

    if value is None or value == previous.filters[index].value:
        return None

    plan = _copy(previous)
    old_condition = plan.filters[index]
    plan.filters[index] = FilterCondition(column, "=", value)

    return FollowUp(
        plan=plan,
        change=(
            f"replaced the filter {_describe(old_condition)} "
            f"with {_describe(plan.filters[index])}"
        ),
    )


def _resolve_value(
    phrase: str,
    literal: str | None,
    column: str,
    columns: dict[str, Any],
) -> str | None:
    """
    The dataset's own spelling of a category value, or None. Unquoted
    values must match one of the column's sampled values (case- and
    separator-insensitively, uniquely); a quoted value is used verbatim.
    Never guesses.
    """

    if column not in _string_dimensions(columns):
        return None

    phrase = _strip_column_phrases(phrase, columns, only=column)

    if phrase == _QUOTE_TOKEN:
        return literal

    if not phrase or _QUOTE_TOKEN in phrase:
        return None

    samples = {
        value
        for value in columns[column].get("sample_values") or []
        if isinstance(value, str) and normalize_column_name(value) == phrase
    }

    return samples.pop() if len(samples) == 1 else None


def _string_dimensions(columns: dict[str, Any]) -> list[str]:
    return [
        name
        for name, info in columns.items()
        if info.get("role") in {"dimension", "categorical"}
        and info.get("data_type") == "string"
    ]


def _strip_column_phrases(
    phrase: str,
    columns: dict[str, Any],
    only: str | None = None,
) -> str:
    """Normalized phrase without a leading "the" or a surrounding column name."""

    phrase = normalize_column_name(phrase)
    phrase = re.sub(r"^the\s+", "", phrase)

    for name in [only] if only else list(columns):
        column_phrase = normalize_column_name(name)

        if phrase.endswith(" " + column_phrase):
            phrase = phrase[: -len(column_phrase)].strip()
        elif phrase.startswith(column_phrase + " "):
            phrase = phrase[len(column_phrase) :].strip()

    return re.sub(r"^the\s+", "", phrase).strip()


def _named_columns(phrase: str, columns: dict[str, Any]) -> set[str]:
    """Columns whose name opens or closes the (normalized) phrase."""

    phrase = re.sub(r"^the\s+", "", normalize_column_name(phrase))

    return {
        name
        for name in columns
        if phrase.endswith(" " + normalize_column_name(name))
        or phrase.startswith(normalize_column_name(name) + " ")
    }


def _describe(condition: FilterCondition) -> str:
    return f"{condition.column} {condition.operator} {json.dumps(condition.value)}"


# =========================================================
# Helpers
# =========================================================


def _normalize(question: str) -> str:
    text = (question or "").lower().strip()
    text = re.sub(r"[?.!,;:]+$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text)


def _only_filler(text: str) -> bool:
    return all(word in _FILLER for word in _words(text))


def _names_column(phrase: str, column: str) -> bool:
    # "the region column" names Region; "region and month" does not.
    normalized = normalize_column_name(phrase)
    normalized = re.sub(r"^the\s+", "", normalized)
    normalized = re.sub(r"\s+column$", "", normalized)

    return normalized == normalize_column_name(column)


def _copy(previous: AnalysisPlan, **changes) -> AnalysisPlan:
    """A new plan; never mutates the (client-supplied) previous one."""

    base = replace(
        previous,
        filters=[
            FilterCondition(f.column, f.operator, f.value) for f in previous.filters
        ],
        group_by=list(previous.group_by),
    )

    return replace(base, **changes)
