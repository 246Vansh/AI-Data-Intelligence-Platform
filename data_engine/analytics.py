import pandas as pd


def sales_summary(df: pd.DataFrame) -> dict:

    sales = df["Weekly_Sales"]

    return {
        "total_sales": float(sales.sum()),
        "average_sales": float(sales.mean()),
        "median_sales": float(sales.median()),
        "minimum_sales": float(sales.min()),
        "maximum_sales": float(sales.max()),
        "standard_deviation": float(sales.std()),
    }


def store_sales(df: pd.DataFrame) -> pd.DataFrame:

    result = (
        df.groupby("Store")["Weekly_Sales"]
        .sum()
        .reset_index()
        .sort_values(
            "Weekly_Sales",
            ascending=False
        )
    )

    return result


def monthly_sales(df: pd.DataFrame) -> pd.DataFrame:

    result = (
        df.assign(
            Month=df["Date"].dt.to_period("M")
        )
        .groupby("Month")["Weekly_Sales"]
        .sum()
        .reset_index()
    )

    result["Month"] = result["Month"].astype(str)

    return result


def holiday_sales_comparison(
    df: pd.DataFrame
) -> pd.DataFrame:

    result = (
        df.groupby("Holiday_Flag")["Weekly_Sales"]
        .agg(
            [
                "count",
                "sum",
                "mean",
                "median",
            ]
        )
        .reset_index()
    )

    return result