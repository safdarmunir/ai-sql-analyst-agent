import pytest

from frontend.api_client import APIError, AnalystAPI
from frontend.charts import build_chart, build_cohort_heatmap


def test_build_bar_chart():
    figure = build_chart(
        rows=[
            {"region": "North", "revenue": 100},
            {"region": "South", "revenue": 80},
        ],
        chart_type="bar",
        x_column="region",
        y_columns=["revenue"],
        title="Revenue by region",
    )

    assert figure is not None
    assert figure.layout.title.text == "Revenue by region"
    assert len(figure.data) == 1


def test_build_chart_rejects_missing_columns():
    figure = build_chart(
        rows=[{"region": "North"}],
        chart_type="bar",
        x_column="region",
        y_columns=["revenue"],
        title="Revenue by region",
    )

    assert figure is None


def test_build_cohort_heatmap():
    figure = build_cohort_heatmap(
        rows=[
            {
                "cohort_month": "2022-01-01",
                "month_number": 0,
                "retention_rate": 100.0,
            },
            {
                "cohort_month": "2022-01-01",
                "month_number": 1,
                "retention_rate": 50.0,
            },
        ],
        title="Retention",
    )

    assert figure is not None
    assert figure.layout.title.text == "Retention"


def test_verify_backend_rejects_wrong_service(monkeypatch):
    api = AnalystAPI("https://wrong.example")
    monkeypatch.setattr(
        api,
        "health",
        lambda: {"status": "ok", "service": "another-app"},
    )

    with pytest.raises(APIError, match="not the AI SQL Analyst backend"):
        api.verify_backend()
