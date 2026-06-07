import pytest

from app.core.config import settings

pytestmark = pytest.mark.anyio


async def upload_sales_dataset(client) -> str:
    csv_data = (
        "order_id,customer,region,revenue\n"
        "1,Acme,North,120.50\n"
        "2,Globex,South,80.00\n"
        "3,Acme,North,40.00\n"
    )
    response = await client.post(
        "/api/v1/datasets/upload",
        files={"file": ("sales.csv", csv_data, "text/csv")},
    )
    assert response.status_code == 201
    return response.json()["dataset_id"]


async def test_get_dataset_schema(client):
    dataset_id = await upload_sales_dataset(client)

    response = await client.get(f"/api/v1/datasets/{dataset_id}/schema")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset_id"] == dataset_id
    assert payload["tables"][0]["name"] == "sales"
    assert payload["tables"][0]["row_count"] == 3


async def test_execute_select_query(client):
    dataset_id = await upload_sales_dataset(client)

    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/query",
        json={
            "sql": (
                "SELECT customer, SUM(revenue) AS total_revenue "
                "FROM sales GROUP BY customer ORDER BY total_revenue DESC"
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["columns"] == ["customer", "total_revenue"]
    assert payload["rows"][0] == {"customer": "Acme", "total_revenue": 160.5}
    assert payload["row_count"] == 2
    assert payload["truncated"] is False


async def test_execute_with_query(client):
    dataset_id = await upload_sales_dataset(client)

    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/query",
        json={
            "sql": (
                "WITH regional AS ("
                "SELECT region, SUM(revenue) AS revenue FROM sales GROUP BY region"
                ") SELECT * FROM regional ORDER BY revenue DESC"
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["rows"][0]["region"] == "North"


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales",
        "DELETE FROM sales",
        "INSERT INTO sales VALUES (4, 'Test', 'West', 10)",
        "SELECT * FROM sales; DROP TABLE sales",
        "SELECT * FROM read_csv('private.csv')",
        "SELECT * FROM read_parquet('private.parquet')",
        "SELECT * FROM query('SELECT * FROM sales')",
        "SELECT * FROM missing_table",
    ],
)
async def test_rejects_unsafe_or_unavailable_sql(client, sql):
    dataset_id = await upload_sales_dataset(client)

    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/query",
        json={"sql": sql},
    )

    assert response.status_code == 400


async def test_query_result_is_capped(client, monkeypatch):
    dataset_id = await upload_sales_dataset(client)
    monkeypatch.setattr(settings, "max_query_rows", 2)

    response = await client.post(
        f"/api/v1/datasets/{dataset_id}/query",
        json={"sql": "SELECT * FROM sales ORDER BY order_id"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["row_count"] == 2
    assert payload["truncated"] is True


async def test_unknown_dataset_returns_404(client):
    response = await client.get(
        "/api/v1/datasets/00000000-0000-0000-0000-000000000000/schema"
    )

    assert response.status_code == 404
