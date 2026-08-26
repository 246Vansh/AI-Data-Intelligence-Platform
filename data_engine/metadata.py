from __future__ import annotations

import re

import pandas as pd

from data_engine.json_safety import make_json_safe


# =========================================================
# CONSTANTS
# =========================================================

STRONG_TIME_TOKENS = {
    "date",
    "timestamp",
    "datetime",
}

WEAK_TIME_TOKENS = {
    "time",
    "created",
    "updated",
    "modified",
    "month",
    "year",
    "day",
    "week",
    "quarter",
    "period",
}

DIMENSION_NAME_TOKENS = {
    "id",
    "code",
    "flag",
    "key",
    "type",
    "category",
    "status",
}


# =========================================================
# HELPERS
# =========================================================


def tokenize_column_name(column_name: str) -> set[str]:
    """
    Split a column name into meaningful tokens.

    Examples:
        order_date     -> {"order", "date"}
        created_at     -> {"created", "at"}
        customer_id    -> {"customer", "id"}
    """

    normalized = str(column_name).strip().lower()

    return {token for token in re.split(r"[_\s\-\.\/]+", normalized) if token}


def get_sample(series: pd.Series, limit: int = 100) -> pd.Series:
    """
    Return a representative non-null sample from a column.
    """

    return series.dropna().head(limit)


# =========================================================
# TIME DETECTION
# =========================================================


def is_time_column(
    series: pd.Series,
    column_name: str,
) -> bool:
    """
    Determine whether a column represents temporal information.

    The detection is intentionally dataset-agnostic.

    Priority:

    1. Existing pandas datetime dtype
    2. Strong temporal column names + parseable values
    3. Weak temporal names + strongly parseable values
    4. Value-based datetime detection without relying on names

    Numeric columns are intentionally not automatically treated
    as dates because values such as 2024, 1, 2, 3, etc. can easily
    produce false positives.
    """

    # -----------------------------------------------------
    # 1. Already a datetime column
    # -----------------------------------------------------

    if pd.api.types.is_datetime64_any_dtype(series):
        return True

    # -----------------------------------------------------
    # Empty columns cannot reliably be classified
    # -----------------------------------------------------

    sample = get_sample(series)

    if sample.empty:
        return False

    # -----------------------------------------------------
    # Numeric columns
    # -----------------------------------------------------
    #
    # Do NOT automatically parse integers/floats as dates.
    #
    # Examples:
    #
    # revenue = 2024
    # year_built = 2020
    # employee_id = 202401
    #
    # These can easily be mistaken for temporal values.
    #
    # If the user has an explicit datetime dtype, pandas will
    # already have identified it above.
    # -----------------------------------------------------

    if pd.api.types.is_numeric_dtype(series):
        return False

    # -----------------------------------------------------
    # Boolean columns
    # -----------------------------------------------------

    if pd.api.types.is_bool_dtype(series):
        return False

    # -----------------------------------------------------
    # Convert sample to strings for parsing
    # -----------------------------------------------------

    sample_as_string = sample.astype(str).str.strip()

    if sample_as_string.empty:
        return False

    # -----------------------------------------------------
    # Attempt datetime parsing
    # -----------------------------------------------------

    parsed = pd.to_datetime(
        sample_as_string,
        errors="coerce",
        format="mixed",
    )

    parse_ratio = float(parsed.notna().mean())

    # -----------------------------------------------------
    # Name evidence
    # -----------------------------------------------------

    tokens = tokenize_column_name(column_name)

    has_strong_name = bool(tokens & STRONG_TIME_TOKENS)
    has_weak_name = bool(tokens & WEAK_TIME_TOKENS)

    # -----------------------------------------------------
    # Strong temporal names
    #
    # Example:
    #
    # order_date
    # created_date
    # event_timestamp
    #
    # Require at least reasonable value evidence.
    # -----------------------------------------------------

    if has_strong_name:
        return parse_ratio >= 0.60

    # -----------------------------------------------------
    # Weak temporal names
    #
    # Example:
    #
    # created
    # updated
    # month
    # period
    #
    # Require stronger value evidence.
    # -----------------------------------------------------

    if has_weak_name:
        return parse_ratio >= 0.80

    # -----------------------------------------------------
    # Pure value-based detection
    #
    # This is the important part for data agnosticism.
    #
    # A column called:
    #
    # "event_start"
    # "recorded_on"
    # "transaction_when"
    #
    # can still be detected if the values themselves are
    # consistently temporal.
    #
    # We use a high threshold to avoid incorrectly classifying
    # arbitrary strings.
    # -----------------------------------------------------

    return parse_ratio >= 0.95


# =========================================================
# COLUMN ROLE DETECTION
# =========================================================


def detect_column_role(
    series: pd.Series,
    column_name: str,
) -> str:
    """
    Determine the semantic role of a column.

    Possible roles:

        time
        metric
        dimension

    The classification is generic and does not assume any
    particular business domain.
    """

    # -----------------------------------------------------
    # Time
    # -----------------------------------------------------

    if is_time_column(
        series,
        column_name,
    ):
        return "time"

    column_tokens = tokenize_column_name(column_name)

    # -----------------------------------------------------
    # Boolean values behave like dimensions
    # -----------------------------------------------------

    if pd.api.types.is_bool_dtype(series):
        return "dimension"

    # -----------------------------------------------------
    # Explicit identifier/category hints (e.g. store_id, product_code)
    # -----------------------------------------------------

    if column_tokens & DIMENSION_NAME_TOKENS:
        return "dimension"

    # -----------------------------------------------------
    # Numeric columns are metrics
    # -----------------------------------------------------

    if pd.api.types.is_numeric_dtype(series):
        return "metric"

    # -----------------------------------------------------
    # Everything else (strings/categorical values) are dimensions
    # -----------------------------------------------------

    return "dimension"


# =========================================================
# DATA TYPE DETECTION
# =========================================================


def detect_data_type(
    series: pd.Series,
) -> str:
    """
    Detect the pandas-level data type.
    """

    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"

    if pd.api.types.is_bool_dtype(series):
        return "boolean"

    if pd.api.types.is_integer_dtype(series):
        return "integer"

    if pd.api.types.is_float_dtype(series):
        return "float"

    if pd.api.types.is_numeric_dtype(series):
        return "numeric"

    return "string"


# =========================================================
# ALLOWED OPERATIONS
# =========================================================


def get_allowed_operations(
    role: str,
) -> list[str]:
    """
    Return operations supported by the detected column role.
    """

    if role == "metric":
        return [
            "sum",
            "mean",
            "median",
            "min",
            "max",
            "count",
        ]

    if role == "dimension":
        return [
            "group_by",
            "filter",
            "count",
        ]

    if role == "time":
        return [
            "group_by",
            "filter",
            "trend",
        ]

    return []


# =========================================================
# COLUMN METADATA
# =========================================================


def build_column_metadata(
    series: pd.Series,
    column_name: str,
) -> dict:
    """
    Build metadata for a single column.
    """

    role = detect_column_role(
        series,
        column_name,
    )

    data_type = detect_data_type(series)

    sample_values = [
        make_json_safe(value) for value in series.dropna().head(5).tolist()
    ]

    return {
        "data_type": data_type,
        "role": role,
        "allowed_operations": get_allowed_operations(role),
        "nullable": bool(series.isna().any()),
        "missing_count": int(series.isna().sum()),
        "unique_values": int(series.nunique(dropna=True)),
        "sample_values": sample_values,
    }


# =========================================================
# METADATA GENERATION
# =========================================================


def get_metadata(
    df: pd.DataFrame,
) -> dict:
    """
    Generate complete dataset metadata.

    This function knows nothing about the dataset domain.

    It can therefore operate on:

        sales
        finance
        HR
        marketing
        logistics
        scientific data
        customer data
        operational data
        etc.
    """

    if not isinstance(df, pd.DataFrame):
        raise TypeError("Metadata generation requires a pandas DataFrame.")

    columns = {}
    time_columns = []

    # -----------------------------------------------------
    # Analyze every column
    # -----------------------------------------------------

    for column in df.columns:
        series = df[column]

        metadata = build_column_metadata(
            series,
            str(column),
        )

        columns[str(column)] = metadata

        if metadata["role"] == "time":
            time_columns.append(str(column))

    # -----------------------------------------------------
    # Determine primary time column
    # -----------------------------------------------------

    time_column = None

    if len(time_columns) == 1:
        time_column = time_columns[0]

    elif len(time_columns) > 1:
        # Prefer an actual datetime dtype.
        datetime_columns = [
            column
            for column in time_columns
            if columns[column]["data_type"] == "datetime"
        ]

        if datetime_columns:
            time_column = datetime_columns[0]

        else:
            time_column = time_columns[0]

    # -----------------------------------------------------
    # Dataset-level statistics
    # -----------------------------------------------------

    return {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": columns,
        # Temporal information
        "time_column": time_column,
        "time_columns": time_columns,
    }
