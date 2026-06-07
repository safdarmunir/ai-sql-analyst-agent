from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

CHART_TYPES = ["none", "bar", "line", "pie", "scatter"]


def build_chart(
    rows: list[dict[str, Any]],
    chart_type: str,
    x_column: str | None,
    y_columns: list[str],
    title: str,
) -> go.Figure | None:
    if not rows or chart_type == "none" or not x_column or not y_columns:
        return None

    dataframe = pd.DataFrame(rows)
    if x_column not in dataframe.columns:
        return None
    valid_y = [column for column in y_columns if column in dataframe.columns]
    if not valid_y:
        return None

    if chart_type == "bar":
        figure = px.bar(dataframe, x=x_column, y=valid_y, title=title, barmode="group")
    elif chart_type == "line":
        figure = px.line(
            dataframe,
            x=x_column,
            y=valid_y,
            title=title,
            markers=True,
        )
    elif chart_type == "pie":
        figure = px.pie(
            dataframe,
            names=x_column,
            values=valid_y[0],
            title=title,
        )
    elif chart_type == "scatter":
        figure = px.scatter(
            dataframe,
            x=x_column,
            y=valid_y[0],
            title=title,
        )
    else:
        return None

    figure.update_layout(
        template="plotly_white",
        margin=dict(l=20, r=20, t=60, b=20),
        legend_title_text="",
    )
    return figure


def build_cohort_heatmap(
    rows: list[dict[str, Any]],
    title: str,
) -> go.Figure | None:
    if not rows:
        return None

    dataframe = pd.DataFrame(rows)
    required = {"cohort_month", "month_number", "retention_rate"}
    if not required.issubset(dataframe.columns):
        return None

    pivot = dataframe.pivot_table(
        index="cohort_month",
        columns="month_number",
        values="retention_rate",
        aggfunc="max",
    ).sort_index()
    if pivot.empty:
        return None

    figure = px.imshow(
        pivot,
        text_auto=".1f",
        aspect="auto",
        color_continuous_scale="Blues",
        title=title,
        labels=dict(x="Months after first purchase", y="Cohort month", color="Retention %"),
    )
    figure.update_layout(
        template="plotly_white",
        margin=dict(l=20, r=20, t=60, b=20),
    )
    return figure
