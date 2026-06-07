from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends

from app.db.duckdb_repository import quote_identifier
from app.schemas.dataset import (
    ColumnProfile,
    DashboardMetric,
    DashboardSection,
    DashboardWidget,
    DatasetDashboardResponse,
    SuggestedQuestion,
    TableProfile,
)
from app.services.query_service import QueryService, get_query_service


SemanticRole = Literal[
    "date",
    "measure",
    "customer_id",
    "order_id",
    "dimension",
    "boolean",
    "identifier",
    "other",
]


class DashboardService:
    def __init__(self, query_service: QueryService) -> None:
        self.query_service = query_service

    async def build_dashboard(self, dataset_id: str) -> DatasetDashboardResponse:
        profiles = await self.query_service.get_profiles(dataset_id)
        table = self._primary_table(profiles)
        table = self._classify_table(table)
        roles = self._roles(table)

        metrics = await self._build_metrics(dataset_id, table, roles)
        sections = [
            await self._overview_section(dataset_id, table, roles),
            await self._sales_section(dataset_id, table, roles),
            await self._acquisition_section(dataset_id, table, roles),
            await self._retention_section(dataset_id, table, roles),
            await self._marketing_section(dataset_id, table, roles),
        ]
        sections = [section for section in sections if section.widgets]

        return DatasetDashboardResponse(
            dataset_id=dataset_id,
            table_name=table.name,
            generated_at=datetime.now(UTC),
            metrics=metrics,
            sections=sections,
            suggested_questions=self._suggest_questions(table, roles),
            profile=table,
        )

    @staticmethod
    def _primary_table(profiles: list[TableProfile]) -> TableProfile:
        return max(profiles, key=lambda table: table.row_count)

    def _classify_table(self, table: TableProfile) -> TableProfile:
        return table.model_copy(
            update={
                "columns": [
                    column.model_copy(
                        update={"semantic_role": self._classify_column(column, table)}
                    )
                    for column in table.columns
                ]
            }
        )

    @staticmethod
    def _classify_column(column: ColumnProfile, table: TableProfile) -> SemanticRole:
        name = column.name.lower()
        compact = name.replace("_", "").replace(" ", "")
        data_type = column.data_type.upper()

        if "BOOL" in data_type:
            return "boolean"
        if any(token in compact for token in ("date", "month", "year", "time")):
            return "date"
        if data_type.startswith("DATE") or data_type.startswith("TIMESTAMP"):
            return "date"

        if any(token in compact for token in ("customerid", "clientid", "buyerid")):
            return "customer_id"
        if any(token in compact for token in ("invoice", "orderid", "orderno", "transactionid")):
            return "order_id"

        numeric = any(
            marker in data_type
            for marker in (
                "INT",
                "DOUBLE",
                "FLOAT",
                "REAL",
                "DECIMAL",
                "NUMERIC",
            )
        )
        measure_terms = (
            "revenue",
            "sales",
            "amount",
            "price",
            "profit",
            "cost",
            "quantity",
            "income",
            "value",
        )
        if numeric and any(token in compact for token in measure_terms):
            return "measure"
        if numeric and "id" in compact:
            return "identifier"

        text_like = any(token in data_type for token in ("VARCHAR", "TEXT", "CHAR"))
        low_cardinality = 1 < column.distinct_count <= max(30, table.row_count // 20)
        if text_like and low_cardinality:
            return "dimension"
        if text_like and any(
            token in compact for token in ("region", "product", "segment", "category", "gender")
        ):
            return "dimension"
        if text_like and ("id" in compact or "code" in compact):
            return "identifier"
        return "other"

    @staticmethod
    def _roles(table: TableProfile) -> dict[str, list[ColumnProfile]]:
        roles: dict[str, list[ColumnProfile]] = {}
        for column in table.columns:
            roles.setdefault(column.semantic_role, []).append(column)
        roles["measure"] = sorted(
            roles.get("measure", []),
            key=lambda column: DashboardService._measure_priority(column.name),
        )
        roles["dimension"] = sorted(
            roles.get("dimension", []),
            key=lambda column: (column.distinct_count, column.name),
        )
        return roles

    @staticmethod
    def _measure_priority(name: str) -> int:
        compact = name.lower().replace(" ", "").replace("_", "")
        priority_terms = [
            "salesamount",
            "revenue",
            "sales",
            "amount",
            "profit",
            "quantity",
            "unitprice",
            "income",
        ]
        for index, term in enumerate(priority_terms):
            if term in compact:
                return index
        return len(priority_terms)

    async def _build_metrics(
        self,
        dataset_id: str,
        table: TableProfile,
        roles: dict[str, list[ColumnProfile]],
    ) -> list[DashboardMetric]:
        metrics = [
            DashboardMetric(label="Rows", value=table.row_count, format="number")
        ]
        measure = self._first(roles, "measure")
        customer = self._first(roles, "customer_id")
        order = self._first(roles, "order_id")
        quoted_table = quote_identifier(table.name)

        if measure:
            result = await self.query_service.execute(
                dataset_id,
                (
                    f"SELECT SUM({quote_identifier(measure.name)}) AS total_value "
                    f"FROM {quoted_table}"
                ),
            )
            value = result.rows[0]["total_value"] if result.rows else None
            metrics.append(
                DashboardMetric(
                    label=f"Total {measure.name}",
                    value=value,
                    format=self._measure_format(measure.name),
                )
            )

        if customer:
            result = await self.query_service.execute(
                dataset_id,
                (
                    f"SELECT COUNT(DISTINCT {quote_identifier(customer.name)}) "
                    f"AS distinct_customers FROM {quoted_table}"
                ),
            )
            metrics.append(
                DashboardMetric(
                    label="Customers",
                    value=result.rows[0]["distinct_customers"] if result.rows else None,
                )
            )

        if order:
            result = await self.query_service.execute(
                dataset_id,
                (
                    f"SELECT COUNT(DISTINCT {quote_identifier(order.name)}) "
                    f"AS distinct_orders FROM {quoted_table}"
                ),
            )
            order_count = result.rows[0]["distinct_orders"] if result.rows else None
            metrics.append(DashboardMetric(label="Orders", value=order_count))
            if measure and order_count:
                value = next(
                    (
                        metric.value
                        for metric in metrics
                        if metric.label == f"Total {measure.name}"
                    ),
                    None,
                )
                if value is not None:
                    metrics.append(
                        DashboardMetric(
                            label="Average Order Value",
                            value=round(value / order_count, 2),
                            format=self._measure_format(measure.name),
                        )
                    )

        return metrics

    async def _overview_section(
        self,
        dataset_id: str,
        table: TableProfile,
        roles: dict[str, list[ColumnProfile]],
    ) -> DashboardSection:
        widgets = []
        date_column = self._first(roles, "date")
        measure = self._first(roles, "measure")
        if date_column and measure:
            widgets.append(
                await self._widget(
                    dataset_id=dataset_id,
                    table=table,
                    key="monthly_trend",
                    title=f"Monthly {measure.name} Trend",
                    description="Tracks performance over time.",
                    question=f"Show monthly trend for {measure.name}.",
                    visualization="line",
                    sql=(
                        "SELECT "
                        f"CAST(date_trunc('month', {quote_identifier(date_column.name)}) AS DATE) "
                        "AS period, "
                        f"SUM({quote_identifier(measure.name)}) AS value "
                        f"FROM {quote_identifier(table.name)} "
                        f"WHERE {quote_identifier(date_column.name)} IS NOT NULL "
                        "GROUP BY 1 ORDER BY 1"
                    ),
                    x_column="period",
                    y_columns=["value"],
                )
            )
        return DashboardSection(
            key="overview",
            title="Executive Overview",
            description="High-level performance and trend signals.",
            widgets=widgets,
        )

    async def _sales_section(
        self,
        dataset_id: str,
        table: TableProfile,
        roles: dict[str, list[ColumnProfile]],
    ) -> DashboardSection:
        widgets = []
        measure = self._first(roles, "measure")
        if measure:
            for dimension in roles.get("dimension", [])[:4]:
                widgets.append(
                    await self._dimension_widget(
                        dataset_id,
                        table,
                        dimension,
                        measure,
                    )
                )
        return DashboardSection(
            key="sales",
            title="Sales Breakdown",
            description="Revenue or measure contribution by business dimension.",
            widgets=widgets,
        )

    async def _acquisition_section(
        self,
        dataset_id: str,
        table: TableProfile,
        roles: dict[str, list[ColumnProfile]],
    ) -> DashboardSection:
        date_column = self._first(roles, "date")
        customer = self._first(roles, "customer_id")
        if not date_column or not customer:
            return DashboardSection(
                key="acquisition",
                title="Customer Acquisition",
                description="New-customer trend based on first purchase date.",
            )

        quoted_table = quote_identifier(table.name)
        sql = f"""
WITH first_purchases AS (
    SELECT
        {quote_identifier(customer.name)} AS customer_id,
        MIN({quote_identifier(date_column.name)}) AS first_purchase_date
    FROM {quoted_table}
    WHERE {quote_identifier(customer.name)} IS NOT NULL
      AND {quote_identifier(date_column.name)} IS NOT NULL
    GROUP BY 1
)
SELECT
    CAST(date_trunc('month', first_purchase_date) AS DATE) AS period,
    COUNT(*) AS new_customers
FROM first_purchases
GROUP BY 1
ORDER BY 1
""".strip()
        widget = await self._widget(
            dataset_id=dataset_id,
            table=table,
            key="new_customers_by_month",
            title="New Customers By Month",
            description="Counts customers by their first observed purchase month.",
            question="Show new customers by first purchase month.",
            visualization="line",
            sql=sql,
            x_column="period",
            y_columns=["new_customers"],
        )
        return DashboardSection(
            key="acquisition",
            title="Customer Acquisition",
            description="New-customer trend based on first purchase date.",
            widgets=[widget],
        )

    async def _retention_section(
        self,
        dataset_id: str,
        table: TableProfile,
        roles: dict[str, list[ColumnProfile]],
    ) -> DashboardSection:
        date_column = self._first(roles, "date")
        customer = self._first(roles, "customer_id")
        if not date_column or not customer:
            return DashboardSection(
                key="retention",
                title="Customer Retention",
                description="Cohort retention by months after first purchase.",
            )

        quoted_table = quote_identifier(table.name)
        sql = f"""
WITH first_purchases AS (
    SELECT
        {quote_identifier(customer.name)} AS customer_id,
        date_trunc('month', MIN({quote_identifier(date_column.name)})) AS cohort_month
    FROM {quoted_table}
    WHERE {quote_identifier(customer.name)} IS NOT NULL
      AND {quote_identifier(date_column.name)} IS NOT NULL
    GROUP BY 1
),
activity AS (
    SELECT DISTINCT
        {quote_identifier(customer.name)} AS customer_id,
        date_trunc('month', {quote_identifier(date_column.name)}) AS activity_month
    FROM {quoted_table}
    WHERE {quote_identifier(customer.name)} IS NOT NULL
      AND {quote_identifier(date_column.name)} IS NOT NULL
),
cohort_sizes AS (
    SELECT cohort_month, COUNT(*) AS cohort_size
    FROM first_purchases
    GROUP BY 1
)
SELECT
    CAST(first_purchases.cohort_month AS DATE) AS cohort_month,
    date_diff('month', first_purchases.cohort_month, activity.activity_month)
        AS month_number,
    COUNT(DISTINCT activity.customer_id) AS retained_customers,
    cohort_sizes.cohort_size,
    ROUND(
        100.0 * COUNT(DISTINCT activity.customer_id) / cohort_sizes.cohort_size,
        2
    ) AS retention_rate
FROM first_purchases
JOIN activity USING (customer_id)
JOIN cohort_sizes USING (cohort_month)
WHERE date_diff('month', first_purchases.cohort_month, activity.activity_month)
      BETWEEN 0 AND 12
GROUP BY 1, 2, 4
ORDER BY 1, 2
""".strip()
        widget = await self._widget(
            dataset_id=dataset_id,
            table=table,
            key="cohort_retention",
            title="Cohort Retention Heatmap",
            description="Tracks retained customers by first-purchase cohort.",
            question="Create a customer cohort retention heatmap.",
            visualization="cohort_heatmap",
            sql=sql,
            x_column="month_number",
            y_columns=["retention_rate"],
        )
        return DashboardSection(
            key="retention",
            title="Customer Retention",
            description="Cohort retention by months after first purchase.",
            widgets=[widget],
        )

    async def _marketing_section(
        self,
        dataset_id: str,
        table: TableProfile,
        roles: dict[str, list[ColumnProfile]],
    ) -> DashboardSection:
        measure = self._first(roles, "measure")
        boolean_column = self._first(roles, "boolean")
        if not measure or not boolean_column:
            return DashboardSection(
                key="marketing",
                title="Marketing Performance",
                description="Campaign or boolean attribute comparison.",
            )
        widget = await self._dimension_widget(
            dataset_id,
            table,
            boolean_column,
            measure,
            key="marketing_comparison",
        )
        return DashboardSection(
            key="marketing",
            title="Marketing Performance",
            description="Campaign or boolean attribute comparison.",
            widgets=[widget],
        )

    async def _dimension_widget(
        self,
        dataset_id: str,
        table: TableProfile,
        dimension: ColumnProfile,
        measure: ColumnProfile,
        key: str | None = None,
    ) -> DashboardWidget:
        safe_key = key or f"{dimension.name.lower().replace(' ', '_')}_breakdown"
        return await self._widget(
            dataset_id=dataset_id,
            table=table,
            key=safe_key,
            title=f"{measure.name} By {dimension.name}",
            description=f"Ranks {dimension.name} by total {measure.name}.",
            question=f"Compare total {measure.name} by {dimension.name}.",
            visualization="bar",
            sql=(
                f"SELECT CAST({quote_identifier(dimension.name)} AS VARCHAR) "
                "AS category, "
                f"SUM({quote_identifier(measure.name)}) AS value "
                f"FROM {quote_identifier(table.name)} "
                f"WHERE {quote_identifier(dimension.name)} IS NOT NULL "
                "GROUP BY 1 ORDER BY value DESC LIMIT 10"
            ),
            x_column="category",
            y_columns=["value"],
        )

    async def _widget(
        self,
        dataset_id: str,
        table: TableProfile,
        key: str,
        title: str,
        description: str,
        question: str,
        visualization: Literal["bar", "line", "pie", "table", "cohort_heatmap"],
        sql: str,
        x_column: str | None,
        y_columns: list[str],
    ) -> DashboardWidget:
        result = await self.query_service.execute(dataset_id, sql)
        return DashboardWidget(
            key=key,
            title=title,
            description=description,
            question=question,
            visualization=visualization,
            result=result,
            x_column=x_column,
            y_columns=y_columns,
        )

    def _suggest_questions(
        self,
        table: TableProfile,
        roles: dict[str, list[ColumnProfile]],
    ) -> list[SuggestedQuestion]:
        questions = []
        measure = self._first(roles, "measure")
        date_column = self._first(roles, "date")
        customer = self._first(roles, "customer_id")
        dimensions = roles.get("dimension", [])

        if measure:
            questions.append(
                SuggestedQuestion(
                    category="Executive",
                    question=f"What is total {measure.name} and average per order?",
                )
            )
        if measure and date_column:
            questions.append(
                SuggestedQuestion(
                    category="Trend",
                    question=f"Show monthly {measure.name} trend.",
                )
            )
        for dimension in dimensions[:4]:
            if measure:
                questions.append(
                    SuggestedQuestion(
                        category="Breakdown",
                        question=f"Which {dimension.name} generated the highest {measure.name}?",
                    )
                )
        if customer and date_column:
            questions.extend(
                [
                    SuggestedQuestion(
                        category="Acquisition",
                        question="Show new customers by first purchase month.",
                    ),
                    SuggestedQuestion(
                        category="Retention",
                        question="Where does customer retention drop the most after first purchase?",
                    ),
                    SuggestedQuestion(
                        category="Retention",
                        question="Which customers bought in one month but not the next month?",
                    ),
                ]
            )
        if len(roles.get("measure", [])) >= 2 and dimensions:
            questions.append(
                SuggestedQuestion(
                    category="Opportunity",
                    question=(
                        f"Which {dimensions[0].name} have high "
                        f"{roles['measure'][0].name} but low {roles['measure'][1].name}?"
                    ),
                )
            )
        if not questions:
            questions.append(
                SuggestedQuestion(
                    category="Starter",
                    question=f"What are the main patterns in {table.name}?",
                )
            )
        return questions[:10]

    @staticmethod
    def _first(
        roles: dict[str, list[ColumnProfile]],
        role: str,
    ) -> ColumnProfile | None:
        values = roles.get(role, [])
        return values[0] if values else None

    @staticmethod
    def _measure_format(name: str) -> Literal["number", "currency", "percentage"]:
        compact = name.lower().replace(" ", "").replace("_", "")
        if any(token in compact for token in ("revenue", "sales", "amount", "price", "cost", "profit", "income")):
            return "currency"
        if "rate" in compact or "percent" in compact:
            return "percentage"
        return "number"


def get_dashboard_service(
    query_service: QueryService = Depends(get_query_service),
) -> DashboardService:
    return DashboardService(query_service)
