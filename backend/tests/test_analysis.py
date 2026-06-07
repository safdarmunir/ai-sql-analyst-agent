import pytest

from app.core.config import settings
from app.main import app
from app.schemas.dataset import (
    BusinessInsight,
    ChartSpec,
    GeneratedSQL,
    ResultInterpretation,
)
from app.services.result_interpreter import get_result_interpreter
from app.services.result_interpreter import ResultInterpretationError
from app.services.sql_generator import get_sql_generator

pytestmark = pytest.mark.anyio


class FakeSQLGenerator:
    def __init__(self, sql_responses: list[str]) -> None:
        self.sql_responses = iter(sql_responses)
        self.calls: list[dict] = []

    async def generate(
        self,
        question,
        tables,
        previous_sql=None,
        error=None,
    ) -> GeneratedSQL:
        self.calls.append(
            {
                "question": question,
                "tables": tables,
                "previous_sql": previous_sql,
                "error": error,
            }
        )
        return GeneratedSQL(sql=next(self.sql_responses))


class FakeResultInterpreter:
    async def interpret(self, question, sql, result):
        return ResultInterpretation(
            chart=ChartSpec(
                chart_type="bar",
                x_column="customer",
                y_columns=["revenue"],
                title="Revenue by customer",
                reason="Compares customer revenue.",
            ),
            insight=BusinessInsight(
                summary="Acme generated the most revenue.",
                key_points=["Acme leads the result."],
                caveats=[],
            ),
        )


class FailingResultInterpreter:
    async def interpret(self, question, sql, result):
        raise ResultInterpretationError("Gemini result interpretation failed.")


async def upload_dataset(client) -> str:
    response = await client.post(
        "/api/v1/datasets/upload",
        files={
            "file": (
                "sales.csv",
                "customer,revenue\nAcme,100\nGlobex,75\nAcme,50\n",
                "text/csv",
            )
        },
    )
    assert response.status_code == 201
    return response.json()["dataset_id"]


async def test_analyze_generates_and_executes_sql(client):
    dataset_id = await upload_dataset(client)
    generator = FakeSQLGenerator(
        ["SELECT customer, SUM(revenue) AS revenue FROM sales GROUP BY customer"]
    )
    app.dependency_overrides[get_sql_generator] = lambda: generator
    app.dependency_overrides[get_result_interpreter] = FakeResultInterpreter

    try:
        response = await client.post(
            f"/api/v1/datasets/{dataset_id}/analyze",
            json={"question": "Which customers generated the most revenue?"},
        )
    finally:
        app.dependency_overrides.pop(get_sql_generator, None)
        app.dependency_overrides.pop(get_result_interpreter, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["correction_attempts"] == 0
    assert payload["generated_sql"].startswith("SELECT customer")
    assert payload["chart"]["chart_type"] == "bar"
    assert payload["insight"]["summary"] == "Acme generated the most revenue."
    assert payload["history_id"] is not None
    assert {row["customer"] for row in payload["result"]["rows"]} == {
        "Acme",
        "Globex",
    }


async def test_analyze_corrects_failed_sql(client):
    dataset_id = await upload_dataset(client)
    generator = FakeSQLGenerator(
        [
            "SELECT invented_column FROM sales",
            "SELECT SUM(revenue) AS total_revenue FROM sales",
        ]
    )
    app.dependency_overrides[get_sql_generator] = lambda: generator
    app.dependency_overrides[get_result_interpreter] = FakeResultInterpreter
    monkeypatch_value = settings.sql_correction_attempts
    settings.sql_correction_attempts = 1

    try:
        response = await client.post(
            f"/api/v1/datasets/{dataset_id}/analyze",
            json={"question": "What is total revenue?"},
        )
    finally:
        settings.sql_correction_attempts = monkeypatch_value
        app.dependency_overrides.pop(get_sql_generator, None)
        app.dependency_overrides.pop(get_result_interpreter, None)

    assert response.status_code == 200
    assert response.json()["correction_attempts"] == 1
    assert len(generator.calls) == 2
    assert generator.calls[1]["previous_sql"] == "SELECT invented_column FROM sales"
    assert "Binder Error" in generator.calls[1]["error"]


async def test_analysis_is_saved_to_history(client):
    dataset_id = await upload_dataset(client)
    generator = FakeSQLGenerator(["SELECT SUM(revenue) AS revenue FROM sales"])
    app.dependency_overrides[get_sql_generator] = lambda: generator
    app.dependency_overrides[get_result_interpreter] = FakeResultInterpreter

    try:
        analysis_response = await client.post(
            f"/api/v1/datasets/{dataset_id}/analyze",
            json={"question": "What is total revenue?"},
        )
        history_response = await client.get(
            f"/api/v1/datasets/{dataset_id}/history"
        )
    finally:
        app.dependency_overrides.pop(get_sql_generator, None)
        app.dependency_overrides.pop(get_result_interpreter, None)

    assert analysis_response.status_code == 200
    assert history_response.status_code == 200
    item = history_response.json()["items"][0]
    assert item["question"] == "What is total revenue?"
    assert item["result"]["rows"][0]["revenue"] == 225.0


async def test_analysis_returns_result_when_interpretation_fails(client):
    dataset_id = await upload_dataset(client)
    generator = FakeSQLGenerator(["SELECT SUM(revenue) AS revenue FROM sales"])
    app.dependency_overrides[get_sql_generator] = lambda: generator
    app.dependency_overrides[get_result_interpreter] = FailingResultInterpreter

    try:
        response = await client.post(
            f"/api/v1/datasets/{dataset_id}/analyze",
            json={"question": "What is total revenue?"},
        )
    finally:
        app.dependency_overrides.pop(get_sql_generator, None)
        app.dependency_overrides.pop(get_result_interpreter, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["rows"][0]["revenue"] == 225.0
    assert payload["chart"]["chart_type"] == "none"
    assert "Gemini result interpretation failed." in payload["insight"]["caveats"]


async def test_analyze_requires_gemini_api_key(client, monkeypatch):
    dataset_id = await upload_dataset(client)
    monkeypatch.setattr(settings, "gemini_api_key", None)

    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/analyze",
        json={"question": "What is total revenue?"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "GEMINI_API_KEY is not configured."


async def test_history_rejects_invalid_dataset_id(client):
    response = await client.get("/api/v1/datasets/not-a-uuid/history")

    assert response.status_code == 404
