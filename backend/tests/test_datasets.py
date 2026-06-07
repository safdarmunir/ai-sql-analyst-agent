import io
import sqlite3

import pytest
from openpyxl import Workbook

from app.core.config import settings

pytestmark = pytest.mark.anyio


async def test_health_check(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ai-sql-analyst-api",
        "version": "0.1.0",
    }


async def test_upload_csv_creates_duckdb_table(client, tmp_path):
    csv_data = (
        "order_id,customer,revenue,order_date\n"
        "1,Acme,120.50,2026-01-05\n"
        "2,Globex,80.00,2026-01-06\n"
    )

    response = await client.post(
        "/api/v1/datasets/upload",
        files={"file": ("Sales Data.csv", csv_data, "text/csv")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["original_filename"] == "Sales Data.csv"
    assert payload["table"]["name"] == "sales_data"
    assert payload["table"]["row_count"] == 2
    assert [column["name"] for column in payload["table"]["columns"]] == [
        "order_id",
        "customer",
        "revenue",
        "order_date",
    ]
    assert len(payload["table"]["sample_rows"]) == 2
    assert (tmp_path / "datasets" / payload["database_filename"]).exists()


async def test_upload_rejects_unsupported_file(client):
    response = await client.post(
        "/api/v1/datasets/upload",
        files={"file": ("sales.pdf", b"not-a-pdf", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith("Supported file types")


async def test_upload_rejects_empty_csv(client):
    response = await client.post(
        "/api/v1/datasets/upload",
        files={"file": ("sales.csv", b"", "text/csv")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded CSV is empty."


async def test_upload_enforces_size_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size_mb", 0)
    response = await client.post(
        "/api/v1/datasets/upload",
        files={"file": ("sales.csv", b"column\nvalue\n", "text/csv")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "File exceeds the 0 MB upload limit."


async def test_upload_excel_creates_table_per_sheet(client):
    workbook = Workbook()
    sales = workbook.active
    sales.title = "Sales Data"
    sales.append(["customer", "revenue"])
    sales.append(["Acme", 100])
    regions = workbook.create_sheet("Regions")
    regions.append(["region", "manager"])
    regions.append(["North", "Sam"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    response = await client.post(
        "/api/v1/datasets/upload",
        files={
            "file": (
                "analytics.xlsx",
                buffer.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["file_type"] == "xlsx"
    assert [table["name"] for table in payload["tables"]] == [
        "sales_data",
        "regions",
    ]


async def test_upload_sqlite_imports_all_user_tables(client, tmp_path):
    sqlite_path = tmp_path / "source.sqlite"
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("CREATE TABLE customers (id INTEGER, name TEXT)")
        connection.execute("INSERT INTO customers VALUES (1, 'Acme')")
        connection.execute("CREATE TABLE orders (id INTEGER, revenue REAL)")
        connection.execute("INSERT INTO orders VALUES (1, 99.5)")

    response = await client.post(
        "/api/v1/datasets/upload",
        files={
            "file": (
                "business.sqlite",
                sqlite_path.read_bytes(),
                "application/x-sqlite3",
            )
        },
    )

    assert response.status_code == 201
    assert [table["name"] for table in response.json()["tables"]] == [
        "customers",
        "orders",
    ]


async def test_list_datasets(client):
    await client.post(
        "/api/v1/datasets/upload",
        files={"file": ("sales.csv", b"value\n1\n", "text/csv")},
    )

    response = await client.get("/api/v1/datasets")

    assert response.status_code == 200
    assert response.json()["datasets"][0]["original_filename"] == "sales.csv"
