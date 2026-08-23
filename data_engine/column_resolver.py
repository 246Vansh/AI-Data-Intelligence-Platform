import re
from typing import Any


# =========================================================
# COLUMN NORMALIZATION
# =========================================================


def normalize_column_name(
    value: str,
) -> str:
    """
    Convert a column/question fragment into a canonical
    comparison form.

    Examples:

        Total_Amount
        total amount
        TOTAL-AMOUNT

    all become:

        total amount
    """

    value = str(value).strip().lower()

    # Replace underscores, hyphens and other separators
    # with spaces.
    value = re.sub(
        r"[_\-/]+",
        " ",
        value,
    )

    # Remove remaining punctuation.
    value = re.sub(
        r"[^\w\s]",
        "",
        value,
    )

    # Collapse repeated whitespace.
    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


# =========================================================
# TOKEN BOUNDARY MATCH
# =========================================================


def _contains_column_phrase(
    question: str,
    normalized_column: str,
) -> bool:
    """
    Check whether the normalized column phrase appears
    as a complete phrase inside the question.

    This prevents unsafe substring matches.

    Example:

        column = "sales"

        "show sales"        -> True
        "show total sales"  -> True
        "show wholesale"    -> False
    """

    question_normalized = normalize_column_name(question)

    pattern = r"(?<!\w)" + re.escape(normalized_column) + r"(?!\w)"

    return (
        re.search(
            pattern,
            question_normalized,
        )
        is not None
    )


# =========================================================
# RESOLVE COLUMN
# =========================================================


def resolve_column(
    question: str,
    columns: dict[str, Any],
    *,
    allowed_roles: set[str] | None = None,
) -> str | None:
    """
    Resolve a user-mentioned column to an actual dataset
    column.

    Resolution is intentionally conservative.

    Returns:
        Actual dataset column name
        OR
        None when no unique safe match exists.

    It NEVER invents a column.
    It NEVER maps business concepts such as
    'revenue' -> some differently named sales column.
    """

    if not question or not columns:
        return None

    candidates: list[str] = []

    normalized_question = normalize_column_name(question)

    # -----------------------------------------------------
    # First pass:
    # Exact normalized column match.
    #
    # This is the safest possible match.
    # -----------------------------------------------------

    for column_name, metadata in columns.items():
        if allowed_roles is not None:
            role = metadata.get("role")

            if role not in allowed_roles:
                continue

        normalized_column = normalize_column_name(column_name)

        if not normalized_column:
            continue

        if normalized_column == normalized_question:
            candidates.append(column_name)

    if len(candidates) == 1:
        return candidates[0]

    # -----------------------------------------------------
    # Second pass:
    # Column phrase appears inside the question.
    # -----------------------------------------------------

    candidates = []

    for column_name, metadata in columns.items():
        if allowed_roles is not None:
            role = metadata.get("role")

            if role not in allowed_roles:
                continue

        normalized_column = normalize_column_name(column_name)

        if not normalized_column:
            continue

        if _contains_column_phrase(
            normalized_question,
            normalized_column,
        ):
            candidates.append(column_name)

    # -----------------------------------------------------
    # Only accept exactly one candidate.
    #
    # Multiple candidates = ambiguous.
    # -----------------------------------------------------

    if len(candidates) != 1:
        return None

    return candidates[0]
