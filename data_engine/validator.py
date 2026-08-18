import pandas as pd


def validate_walmart_data(df: pd.DataFrame) -> dict:
    """
    Validate the cleaned Walmart dataset.
    Returns a structured validation report.
    """

    issues = []
    warnings = []

    # --------------------------------------------------
    # 1. Check required columns
    # --------------------------------------------------

    required_columns = {
        "Store",
        "Date",
        "Weekly_Sales",
        "Holiday_Flag",
        "Temperature",
        "Fuel_Price",
        "CPI",
        "Unemployment",
    }

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        issues.append({
            "type": "missing_columns",
            "columns": list(missing_columns),
        })

    # --------------------------------------------------
    # 2. Check missing values
    # --------------------------------------------------

    missing_values = df.isna().sum()

    for column, count in missing_values.items():

        if count > 0:
            issues.append({
                "type": "missing_values",
                "column": column,
                "count": int(count),
            })

    # --------------------------------------------------
    # 3. Check duplicate rows
    # --------------------------------------------------

    duplicate_count = int(df.duplicated().sum())

    if duplicate_count > 0:
        warnings.append({
            "type": "duplicate_rows",
            "count": duplicate_count,
        })

    # --------------------------------------------------
    # 4. Validate dates
    # --------------------------------------------------

    invalid_dates = df["Date"].isna().sum()

    if invalid_dates > 0:
        issues.append({
            "type": "invalid_dates",
            "count": int(invalid_dates),
        })

    # --------------------------------------------------
    # 5. Validate Holiday_Flag
    # --------------------------------------------------

    invalid_holiday_flags = ~df["Holiday_Flag"].isin([0, 1])

    invalid_holiday_count = int(
        invalid_holiday_flags.sum()
    )

    if invalid_holiday_count > 0:
        issues.append({
            "type": "invalid_holiday_flag",
            "count": invalid_holiday_count,
        })

    # --------------------------------------------------
    # 6. Validate Weekly_Sales
    # --------------------------------------------------

    negative_sales = df["Weekly_Sales"] < 0

    negative_sales_count = int(
        negative_sales.sum()
    )

    if negative_sales_count > 0:
        issues.append({
            "type": "negative_sales",
            "count": negative_sales_count,
        })

    # --------------------------------------------------
    # 7. Validate Store IDs
    # --------------------------------------------------

    if (df["Store"] <= 0).any():

        invalid_store_count = int(
            (df["Store"] <= 0).sum()
        )

        issues.append({
            "type": "invalid_store_id",
            "count": invalid_store_count,
        })

    # --------------------------------------------------
    # 8. Date range
    # --------------------------------------------------

    date_range = {
        "minimum": df["Date"].min(),
        "maximum": df["Date"].max(),
    }

    # --------------------------------------------------
    # 9. Return validation report
    # --------------------------------------------------

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "duplicate_rows": duplicate_count,
        "date_range": date_range,
    }