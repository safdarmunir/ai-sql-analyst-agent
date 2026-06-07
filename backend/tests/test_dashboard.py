import pytest

pytestmark = pytest.mark.anyio


async def upload_adventure_like_dataset(client) -> str:
    csv_data = (
        "Purchase Date,Invoice No,Customer ID,Product,Region,"
        "Customer Segments,Sales Amount,Quantity,Marketing Email Sent\n"
        "2022-01-01,1001,1,Road Bikes,Asia,Retail Stores,100,2,true\n"
        "2022-01-15,1002,2,Accessories,Europe,Individual Customers,60,1,false\n"
        "2022-02-05,1003,1,Road Bikes,Asia,Retail Stores,120,3,true\n"
        "2022-02-20,1004,3,Mountain Bikes,North America,Retail Stores,90,1,true\n"
        "2022-03-02,1005,2,Accessories,Europe,Individual Customers,80,2,false\n"
    )
    response = await client.post(
        "/api/v1/datasets/upload",
        files={"file": ("adventure.csv", csv_data, "text/csv")},
    )
    assert response.status_code == 201
    return response.json()["dataset_id"]


async def test_dashboard_builds_semantic_widgets(client):
    dataset_id = await upload_adventure_like_dataset(client)

    response = await client.get(f"/api/v1/datasets/{dataset_id}/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["table_name"] == "adventure"
    assert any(metric["label"] == "Total Sales Amount" for metric in payload["metrics"])
    assert any(
        question["category"] == "Retention"
        for question in payload["suggested_questions"]
    )

    section_keys = {section["key"] for section in payload["sections"]}
    assert {"overview", "sales", "acquisition", "retention", "marketing"}.issubset(
        section_keys
    )

    widgets = [
        widget
        for section in payload["sections"]
        for widget in section["widgets"]
    ]
    assert any(widget["visualization"] == "cohort_heatmap" for widget in widgets)
    assert all(
        widget["result"]["sql"].lstrip().upper().startswith(("SELECT", "WITH"))
        for widget in widgets
    )


async def test_dashboard_rejects_unknown_dataset(client):
    response = await client.get(
        "/api/v1/datasets/00000000-0000-0000-0000-000000000000/dashboard"
    )

    assert response.status_code == 404
