import os
from typing import Any

import pandas as pd
import streamlit as st

from api_client import APIError, AnalystAPI
from charts import CHART_TYPES, build_chart, build_cohort_heatmap

DEFAULT_API_BASE_URL = "https://backend-production-f3c5.up.railway.app"


def get_api_base_url() -> str:
    try:
        secret_value = st.secrets.get("API_BASE_URL")
    except Exception:
        secret_value = None
    configured_url = os.getenv("API_BASE_URL") or secret_value or DEFAULT_API_BASE_URL
    return configured_url.rstrip("/")


API_BASE_URL = get_api_base_url()
api = AnalystAPI(API_BASE_URL)

st.set_page_config(
    page_title="AI SQL Analyst Agent",
    page_icon=None,
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1280px; padding-top: 2rem;}
    [data-testid="stSidebar"] {background: #f7f8fa;}
    .hero {
        padding: 1.4rem 1.6rem;
        border: 1px solid #e4e7ec;
        border-radius: 14px;
        background: linear-gradient(135deg, #ffffff 0%, #f3f7ff 100%);
        margin-bottom: 1.2rem;
    }
    .eyebrow {color: #155eef; font-weight: 700; letter-spacing: .08em;}
    .muted {color: #667085;}
    </style>
    """,
    unsafe_allow_html=True,
)


def initialize_state() -> None:
    defaults = {
        "dataset_id": None,
        "dataset_name": None,
        "schema": None,
        "analysis": None,
        "dashboard": None,
        "manual_result": None,
        "question_text": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def load_dataset(dataset_id: str, dataset_name: str) -> None:
    st.session_state.dataset_id = dataset_id
    st.session_state.dataset_name = dataset_name
    st.session_state.schema = api.get_schema(dataset_id)
    st.session_state.analysis = None
    st.session_state.dashboard = None
    st.session_state.manual_result = None
    st.session_state.question_text = ""


def render_table_schema(table: dict[str, Any]) -> None:
    st.markdown(f"**{table['name']}** · {table['row_count']:,} rows")
    column_frame = pd.DataFrame(table["columns"])
    st.dataframe(column_frame, width="stretch", hide_index=True)
    if table["sample_rows"]:
        st.caption("Sample rows")
        st.dataframe(
            pd.DataFrame(table["sample_rows"]),
            width="stretch",
            hide_index=True,
        )


def render_result(result: dict[str, Any]) -> None:
    metric_columns = st.columns(3)
    metric_columns[0].metric("Rows returned", result["row_count"])
    metric_columns[1].metric(
        "Execution",
        f"{result['execution_time_ms']:.1f} ms",
    )
    metric_columns[2].metric("Truncated", "Yes" if result["truncated"] else "No")
    st.dataframe(
        pd.DataFrame(result["rows"], columns=result["columns"]),
        width="stretch",
        hide_index=True,
    )


def format_metric_value(value: Any, value_format: str) -> str:
    if value is None:
        return "N/A"
    if value_format == "currency":
        return f"${float(value):,.0f}"
    if value_format == "percentage":
        return f"{float(value):,.1f}%"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def render_dashboard_widget(widget: dict[str, Any]) -> None:
    st.markdown(f"**{widget['title']}**")
    st.caption(widget["description"])
    result = widget["result"]

    if widget["visualization"] == "cohort_heatmap":
        figure = build_cohort_heatmap(result["rows"], widget["title"])
    else:
        figure = build_chart(
            result["rows"],
            widget["visualization"],
            widget["x_column"],
            widget["y_columns"],
            widget["title"],
        )

    if figure is not None:
        st.plotly_chart(figure, width="stretch")
    else:
        render_result(result)

    with st.expander("Dashboard SQL"):
        st.code(result["sql"], language="sql")


def render_analysis(analysis: dict[str, Any]) -> None:
    st.subheader("Answer")
    st.write(analysis["insight"]["summary"])
    if analysis["insight"]["key_points"]:
        for point in analysis["insight"]["key_points"]:
            st.markdown(f"- {point}")
    if analysis["insight"]["caveats"]:
        with st.expander("Caveats"):
            for caveat in analysis["insight"]["caveats"]:
                st.markdown(f"- {caveat}")

    with st.expander("Generated SQL", expanded=True):
        st.code(analysis["generated_sql"], language="sql")
        if analysis["correction_attempts"]:
            st.caption(
                f"SQL was corrected {analysis['correction_attempts']} time(s)."
            )

    result = analysis["result"]
    render_result(result)

    chart = analysis["chart"]
    columns = result["columns"]
    if columns:
        with st.expander("Chart controls", expanded=chart["chart_type"] != "none"):
            selected_type = st.selectbox(
                "Chart type",
                CHART_TYPES,
                index=CHART_TYPES.index(chart["chart_type"]),
                key=f"chart_type_{analysis.get('history_id')}",
            )
            selected_x = st.selectbox(
                "X column",
                [None, *columns],
                index=(
                    [None, *columns].index(chart["x_column"])
                    if chart["x_column"] in columns
                    else 0
                ),
                key=f"chart_x_{analysis.get('history_id')}",
            )
            default_y = [
                column for column in chart["y_columns"] if column in columns
            ]
            selected_y = st.multiselect(
                "Y columns",
                columns,
                default=default_y,
                key=f"chart_y_{analysis.get('history_id')}",
            )
            chart_title = st.text_input(
                "Chart title",
                value=chart["title"],
                key=f"chart_title_{analysis.get('history_id')}",
            )

        figure = build_chart(
            result["rows"],
            selected_type,
            selected_x,
            selected_y,
            chart_title,
        )
        if figure is not None:
            st.plotly_chart(figure, width="stretch")


initialize_state()

st.markdown(
    """
    <div class="hero">
      <div class="eyebrow">AI SQL ANALYST</div>
      <h1>Ask business questions. Get safe SQL and clear answers.</h1>
      <div class="muted">
        Upload CSV, Excel, or SQLite data. The agent reads the schema,
        generates guarded DuckDB SQL, executes it, and explains the result.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    backend_health = api.verify_backend()
except APIError as exc:
    st.error(str(exc))
    st.code(
        f'API_BASE_URL = "{DEFAULT_API_BASE_URL}"',
        language="toml",
    )
    st.caption(f"Currently configured backend: {API_BASE_URL}")
    st.stop()

with st.sidebar:
    st.header("Dataset")
    uploaded_file = st.file_uploader(
        "Upload data",
        type=["csv", "xlsx", "sqlite", "sqlite3", "db"],
        help="Maximum size is configured by the backend.",
    )
    if st.button(
        "Import dataset",
        type="primary",
        width="stretch",
        disabled=uploaded_file is None,
    ):
        try:
            with st.spinner("Creating DuckDB tables..."):
                payload = api.upload_dataset(uploaded_file)
                load_dataset(payload["dataset_id"], payload["original_filename"])
            st.success(f"Imported {len(payload['tables'])} table(s).")
        except APIError as exc:
            st.error(str(exc))

    st.divider()
    try:
        datasets = api.list_datasets()
    except APIError:
        datasets = []

    if datasets:
        labels = {
            f"{item['original_filename']} · {item['file_type'].upper()}": item
            for item in datasets
        }
        current_index = 0
        for index, item in enumerate(labels.values()):
            if item["dataset_id"] == st.session_state.dataset_id:
                current_index = index
                break
        selected_label = st.selectbox(
            "Recent datasets",
            list(labels),
            index=current_index,
        )
        selected_dataset = labels[selected_label]
        if st.button("Open dataset", width="stretch"):
            try:
                load_dataset(
                    selected_dataset["dataset_id"],
                    selected_dataset["original_filename"],
                )
            except APIError as exc:
                st.error(str(exc))

    st.caption(
        f"Backend: {API_BASE_URL}\n\n"
        f"Service: {backend_health['service']} v{backend_health['version']}"
    )

if not st.session_state.dataset_id:
    st.info("Upload or open a dataset to begin.")
    st.stop()

st.caption(
    f"Active dataset: {st.session_state.dataset_name} · "
    f"ID {st.session_state.dataset_id}"
)

dashboard_tab, analysis_tab, schema_tab, sql_tab, history_tab = st.tabs(
    ["Dashboard", "Ask the agent", "Schema", "SQL workspace", "History"]
)

with dashboard_tab:
    if st.session_state.dashboard is None:
        try:
            with st.spinner("Profiling dataset and building dashboard..."):
                st.session_state.dashboard = api.get_dashboard(
                    st.session_state.dataset_id
                )
        except APIError as exc:
            st.error(str(exc))

    dashboard = st.session_state.dashboard
    if dashboard:
        st.subheader("Auto Dashboard")
        st.caption(
            f"Primary table: {dashboard['table_name']} - "
            f"Generated: {dashboard['generated_at']}"
        )

        if dashboard["metrics"]:
            metric_columns = st.columns(min(len(dashboard["metrics"]), 4))
            for index, metric in enumerate(dashboard["metrics"]):
                metric_columns[index % len(metric_columns)].metric(
                    metric["label"],
                    format_metric_value(metric["value"], metric["format"]),
                )

        st.markdown("### Suggested questions")
        suggestion_columns = st.columns(2)
        for index, item in enumerate(dashboard["suggested_questions"]):
            if suggestion_columns[index % 2].button(
                item["question"],
                key=f"suggest_{index}",
                width="stretch",
            ):
                st.session_state.question_text = item["question"]
                st.session_state.analysis = None

        for section in dashboard["sections"]:
            with st.expander(section["title"], expanded=True):
                st.caption(section["description"])
                for widget in section["widgets"]:
                    render_dashboard_widget(widget)
                    st.divider()

with analysis_tab:
    examples = [
        "Top 10 customers by revenue",
        "Compare revenue by region",
        "Show monthly revenue trend",
        "Which products are declining month over month?",
    ]
    question = st.text_area(
        "Business question",
        placeholder="Which products generated the highest revenue?",
        height=100,
        key="question_text",
    )
    st.caption("Examples: " + " · ".join(examples))

    if st.button(
        "Analyze",
        type="primary",
        disabled=len(question.strip()) < 3,
    ):
        try:
            with st.spinner("Reading schema, generating SQL, and analyzing results..."):
                st.session_state.analysis = api.analyze(
                    st.session_state.dataset_id,
                    question.strip(),
                )
        except APIError as exc:
            st.error(str(exc))

    if st.session_state.analysis:
        render_analysis(st.session_state.analysis)

with schema_tab:
    schema = st.session_state.schema
    if schema is None:
        try:
            schema = api.get_schema(st.session_state.dataset_id)
            st.session_state.schema = schema
        except APIError as exc:
            st.error(str(exc))
            schema = {"tables": []}
    for table in schema["tables"]:
        with st.expander(table["name"], expanded=len(schema["tables"]) == 1):
            render_table_schema(table)

with sql_tab:
    st.warning("Only one SELECT or WITH query is accepted.")
    manual_sql = st.text_area(
        "Read-only SQL",
        placeholder="SELECT * FROM table_name LIMIT 20",
        height=180,
    )
    if st.button(
        "Run SQL",
        disabled=not manual_sql.strip(),
    ):
        try:
            st.session_state.manual_result = api.execute_sql(
                st.session_state.dataset_id,
                manual_sql,
            )
        except APIError as exc:
            st.error(str(exc))
    if st.session_state.manual_result:
        render_result(st.session_state.manual_result)

with history_tab:
    try:
        history = api.get_history(st.session_state.dataset_id)
    except APIError as exc:
        st.error(str(exc))
        history = []

    if not history:
        st.info("No saved analyses yet.")
    for item in history:
        with st.expander(f"{item['question']} · {item['created_at']}"):
            st.write(item["insight"]["summary"] if item["insight"] else "")
            st.code(item["generated_sql"], language="sql")
            render_result(item["result"])
