import pandas as pd


def clean_walmart_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and validate the Walmart dataset.
    Returns a new DataFrame without modifying the original.
    """

    cleaned_df = df.copy()

    # Convert Date from string to datetime
    cleaned_df["Date"] = pd.to_datetime(
        cleaned_df["Date"],
        dayfirst=True,
        errors="coerce"
    )

    # Validate Holiday_Flag
    valid_holiday_values = {0, 1}

    invalid_holiday_values = (
        ~cleaned_df["Holiday_Flag"].isin(valid_holiday_values)
    )

    if invalid_holiday_values.any():
        raise ValueError(
            "Holiday_Flag contains values other than 0 and 1."
        )

    # Weekly sales should not be negative
    if (cleaned_df["Weekly_Sales"] < 0).any():
        raise ValueError(
            "Weekly_Sales contains negative values."
        )

    return cleaned_df