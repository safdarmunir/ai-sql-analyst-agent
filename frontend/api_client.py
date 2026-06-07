from typing import Any

import requests


class APIError(RuntimeError):
    pass


class AnalystAPI:
    EXPECTED_SERVICE = "ai-sql-analyst-api"

    def __init__(self, base_url: str, timeout_seconds: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def verify_backend(self) -> dict[str, Any]:
        health = self.health()
        if health.get("service") != self.EXPECTED_SERVICE:
            raise APIError(
                "The configured API_BASE_URL is not the AI SQL Analyst backend. "
                "Update the Streamlit Cloud secret to your Railway backend URL."
            )
        return health

    def list_datasets(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/v1/datasets")
        return payload["datasets"]

    def upload_dataset(self, uploaded_file) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/datasets/upload",
            files={
                "file": (
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    uploaded_file.type or "application/octet-stream",
                )
            },
        )

    def get_schema(self, dataset_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/schema")

    def get_dashboard(self, dataset_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/datasets/{dataset_id}/dashboard")

    def analyze(self, dataset_id: str, question: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/analyze",
            json={"question": question},
        )

    def execute_sql(self, dataset_id: str, sql: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/query",
            json={"sql": sql},
        )

    def get_history(self, dataset_id: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"/api/v1/datasets/{dataset_id}/history",
        )
        return payload["items"]

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise APIError(
                "Could not reach the FastAPI backend. Check that it is running."
            ) from exc

        if response.ok:
            return response.json()

        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        if isinstance(detail, dict):
            detail = detail.get("message") or str(detail)
        raise APIError(f"{response.status_code}: {detail}")
