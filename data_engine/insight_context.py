import pandas as pd


def build_insight_context(
    result: pd.DataFrame,
    metric_column: str,
    group_by: list[str],
) -> dict:

    context = {
        "row_count": len(result),
        "metric_column": metric_column,
        "group_by": group_by,
    }

    if result.empty:
        return context

    if metric_column not in result.columns:
        return context

    metric = result[metric_column]

    max_index = metric.idxmax()
    min_index = metric.idxmin()

    context["highest"] = {
        "value": float(result.loc[max_index, metric_column]),
        "row": (result.loc[max_index].to_dict()),
    }

    context["lowest"] = {
        "value": float(result.loc[min_index, metric_column]),
        "row": (result.loc[min_index].to_dict()),
    }

    context["difference"] = float(metric.max() - metric.min())

    return context
