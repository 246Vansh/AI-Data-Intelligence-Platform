"""
Bounded follow-up interpretation for /api/analyze (Step 96).

Applies ONE narrow, explicit edit to the most recent successful plan:

- ranking: "make it the bottom 10 instead", "top 3"
  -> sort direction + limit (sort_by metric);
- grouping: "break that down by region" (adds a column),
  "by city instead" (replaces the grouping).

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

# Explicit references back to the previous analysis. Deliberately
# narrow: a pronoun alone ("orders that shipped") is not a reference.
_REFERENCE = re.compile(
    r"\binstead\b"
    r"|\b(?:break|split)\s+(?:it|that|this|these|those|them)\s+down\b"
    r"|\b(?:what|how)\s+about\b"
    r"|^(?:now\s+|and\s+|also\s+)?"
    r"(?:make|change|switch|turn|sort|show|do|keep|limit)\s+(?:it|that|this|them)\b"
    r"|\b(?:same|previous|last)\s+(?:analysis|result|results|question|chart|query)\b"
)


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

    ranking = _resolve_ranking(text, previous)
    grouping = _resolve_grouping(text, previous, metadata.get("columns") or {})

    # One edit per follow-up; two matches means the message says more
    # than either edit alone covers.
    if ranking is not None and grouping is not None:
        return None

    return ranking or grouping


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
