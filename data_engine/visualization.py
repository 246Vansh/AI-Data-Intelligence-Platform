def create_visualization_spec(
    result,
    visualization_type: str,
    title: str | None = None,
):
    columns = result.columns.tolist()

    # -----------------------------------------
    # Validate visualization type
    # -----------------------------------------

    allowed_visualizations = {
        "bar",
        "line",
        "pie",
        "scatter",
        "table",
    }

    if visualization_type not in allowed_visualizations:
        raise ValueError(
            f"Unsupported visualization: "
            f"{visualization_type}"
        )

    # -----------------------------------------
    # Table visualization
    # -----------------------------------------

    # Tables can contain one column.
    if visualization_type == "table":

        if title is None:
            title = "Analysis Results"

        return {
            "type": "table",
            "title": title,
            "encoding": {
                "columns": columns,
            },
        }

    # -----------------------------------------
    # Chart visualizations
    # -----------------------------------------

    if len(columns) < 2:

        raise ValueError(
            "Chart visualization requires "
            "at least two columns."
        )

    x_column = columns[0]
    y_column = columns[1]

    # -----------------------------------------
    # Default title
    # -----------------------------------------

    if title is None:

        title = (
            f"{y_column} by {x_column}"
        )

    # -----------------------------------------
    # Chart visualization spec
    # -----------------------------------------

    return {
        "type": visualization_type,
        "title": title,
        "encoding": {
            "x": x_column,
            "y": y_column,
        },
    }