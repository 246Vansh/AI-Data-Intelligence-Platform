from __future__ import annotations

from typing import Any

import pandas as pd


# =========================================================
# DATA QUALITY ENGINE
# =========================================================
#
# Dataset-independent quality analysis.
#
# It does NOT:
#   - modify the DataFrame
#   - assume business-specific columns
#   - assume Walmart fields
#   - execute analysis plans
#
# It only detects potential quality issues.
# =========================================================


def check_data_quality(
    df: pd.DataFrame,
) -> dict[str, Any]:

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df must be a pandas DataFrame.")

    if df.empty:
        return {
            "status": "invalid",
            "issue_count": 1,
            "issues": [
                {
                    "type": "empty_dataset",
                    "severity": "error",
                    "message": "Dataset contains no rows.",
                }
            ],
        }

    issues: list[dict[str, Any]] = []

    # -----------------------------------------------------
    # Duplicate rows
    # -----------------------------------------------------

    duplicate_count = int(df.duplicated().sum())

    if duplicate_count > 0:
        issues.append(
            {
                "type": "duplicate_rows",
                "severity": "warning",
                "count": duplicate_count,
                "message": (f"Dataset contains {duplicate_count} duplicate rows."),
            }
        )

    # -----------------------------------------------------
    # Column-level checks
    # -----------------------------------------------------

    for column in df.columns:
        series = df[column]

        # ---------------------------------------------
        # Missing values
        # ---------------------------------------------

        missing_count = int(series.isna().sum())

        if missing_count > 0:
            missing_percentage = (missing_count / len(df)) * 100

            severity = _missing_severity(missing_percentage)

            issues.append(
                {
                    "type": "missing_values",
                    "severity": severity,
                    "column": column,
                    "count": missing_count,
                    "percentage": round(
                        missing_percentage,
                        2,
                    ),
                    "message": (
                        f"Column '{column}' contains "
                        f"{missing_count} missing values "
                        f"({missing_percentage:.2f}%)."
                    ),
                }
            )

        # ---------------------------------------------
        # Constant column
        # ---------------------------------------------

        unique_count = int(series.nunique(dropna=True))

        if unique_count <= 1:
            issues.append(
                {
                    "type": "constant_column",
                    "severity": "warning",
                    "column": column,
                    "unique_count": unique_count,
                    "message": (
                        f"Column '{column}' contains {unique_count} unique value."
                    ),
                }
            )

        # ---------------------------------------------
        # High cardinality
        # ---------------------------------------------

        if len(df) > 0:
            cardinality_percentage = (unique_count / len(df)) * 100

            if cardinality_percentage >= 95 and unique_count > 20:
                issues.append(
                    {
                        "type": "high_cardinality",
                        "severity": "info",
                        "column": column,
                        "unique_count": unique_count,
                        "percentage": round(
                            cardinality_percentage,
                            2,
                        ),
                        "message": (f"Column '{column}' has very high cardinality."),
                    }
                )

        # ---------------------------------------------
        # Numeric outliers
        # ---------------------------------------------
        outlier_count = 0

        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(
            series
        ):
            outlier_count = _count_iqr_outliers(series)

        if outlier_count > 0:
            issues.append(
                {
                    "type": "numeric_outliers",
                    "severity": "info",
                    "column": column,
                    "count": outlier_count,
                    "message": (
                        f"Column '{column}' contains "
                        f"{outlier_count} potential "
                        f"IQR outliers."
                    ),
                }
            )

    # -----------------------------------------------------
    # Determine overall status
    # -----------------------------------------------------

    status = _determine_status(issues)

    return {
        "status": status,
        "issue_count": len(issues),
        "issues": issues,
    }


# =========================================================
# MISSING VALUE SEVERITY
# =========================================================


def _missing_severity(
    percentage: float,
) -> str:

    if percentage >= 50:
        return "error"

    if percentage >= 20:
        return "warning"

    return "info"


# =========================================================
# IQR OUTLIER DETECTION
# =========================================================


def _count_iqr_outliers(series: pd.Series) -> int:

    if not pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return 0

    values = series.dropna()

    if values.empty:
        return 0

    if values.nunique() < 2:
        return 0

    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)

    iqr = q3 - q1

    if iqr == 0:
        return 0

    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr

    return int(((values < lower_bound) | (values > upper_bound)).sum())


# =========================================================
# OVERALL STATUS
# =========================================================


def _determine_status(
    issues: list[dict[str, Any]],
) -> str:

    severities = {issue["severity"] for issue in issues}

    if "error" in severities:
        return "error"

    if "warning" in severities:
        return "warning"

    if issues:
        return "info"

    return "healthy"
