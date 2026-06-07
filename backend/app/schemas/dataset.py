from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ColumnSchema(BaseModel):
    name: str
    data_type: str
    nullable: bool


class TableSchema(BaseModel):
    name: str
    row_count: int = Field(ge=0)
    columns: list[ColumnSchema]
    sample_rows: list[dict[str, Any]]


class DatasetUploadResponse(BaseModel):
    dataset_id: str
    original_filename: str
    database_filename: str
    file_type: str
    tables: list[TableSchema]
    table: TableSchema | None = None


class DatasetSummary(BaseModel):
    dataset_id: str
    original_filename: str
    file_type: str
    table_count: int = Field(ge=0)
    created_at: datetime


class DatasetListResponse(BaseModel):
    datasets: list[DatasetSummary]


class DatasetSchemaResponse(BaseModel):
    dataset_id: str
    tables: list[TableSchema]


class SQLQueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=50_000)


class SQLQueryResponse(BaseModel):
    sql: str
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int = Field(ge=0)
    truncated: bool
    execution_time_ms: float = Field(ge=0)


class NaturalLanguageQueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2_000)


class GeneratedSQL(BaseModel):
    sql: str = Field(description="One DuckDB SELECT or WITH query.")


class ChartSpec(BaseModel):
    chart_type: Literal["none", "bar", "line", "pie", "scatter"] = "none"
    x_column: str | None = None
    y_columns: list[str] = Field(default_factory=list)
    title: str = ""
    reason: str = ""


class BusinessInsight(BaseModel):
    summary: str
    key_points: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class ResultInterpretation(BaseModel):
    chart: ChartSpec
    insight: BusinessInsight


class AnalysisResponse(BaseModel):
    question: str
    generated_sql: str
    result: SQLQueryResponse
    chart: ChartSpec
    insight: BusinessInsight
    correction_attempts: int = Field(ge=0)
    history_id: int | None = None


class QueryHistoryItem(BaseModel):
    history_id: int
    dataset_id: str
    question: str
    generated_sql: str
    result: SQLQueryResponse
    chart: ChartSpec | None = None
    insight: BusinessInsight | None = None
    correction_attempts: int = Field(ge=0)
    created_at: datetime


class QueryHistoryResponse(BaseModel):
    items: list[QueryHistoryItem]


class ColumnProfile(BaseModel):
    name: str
    data_type: str
    semantic_role: Literal[
        "date",
        "measure",
        "customer_id",
        "order_id",
        "dimension",
        "boolean",
        "identifier",
        "other",
    ]
    distinct_count: int = Field(ge=0)
    null_count: int = Field(ge=0)
    minimum: Any | None = None
    maximum: Any | None = None


class TableProfile(BaseModel):
    name: str
    row_count: int = Field(ge=0)
    columns: list[ColumnProfile]


class SuggestedQuestion(BaseModel):
    category: str
    question: str


class DashboardMetric(BaseModel):
    label: str
    value: Any
    format: Literal["number", "currency", "percentage"] = "number"


class DashboardWidget(BaseModel):
    key: str
    title: str
    description: str
    question: str
    visualization: Literal["bar", "line", "pie", "table", "cohort_heatmap"]
    result: SQLQueryResponse
    x_column: str | None = None
    y_columns: list[str] = Field(default_factory=list)


class DashboardSection(BaseModel):
    key: str
    title: str
    description: str
    widgets: list[DashboardWidget] = Field(default_factory=list)


class DatasetDashboardResponse(BaseModel):
    dataset_id: str
    table_name: str
    generated_at: datetime
    metrics: list[DashboardMetric]
    sections: list[DashboardSection]
    suggested_questions: list[SuggestedQuestion]
    profile: TableProfile
