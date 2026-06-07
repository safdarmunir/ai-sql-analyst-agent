import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.schemas.dataset import DatasetSummary
from app.schemas.dataset import (
    BusinessInsight,
    ChartSpec,
    QueryHistoryItem,
    SQLQueryResponse,
)


class MetadataRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    database_filename TEXT NOT NULL,
                    table_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS query_history (
                    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dataset_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    generated_sql TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    chart_json TEXT,
                    insight_json TEXT,
                    correction_attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
                );

                CREATE INDEX IF NOT EXISTS idx_history_dataset_created
                ON query_history(dataset_id, created_at DESC);
                """
            )

    def save_dataset(
        self,
        dataset_id: str,
        original_filename: str,
        file_type: str,
        database_filename: str,
        table_count: int,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO datasets (
                    dataset_id,
                    original_filename,
                    file_type,
                    database_filename,
                    table_count,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    original_filename,
                    file_type,
                    database_filename,
                    table_count,
                    created_at,
                ),
            )

    def list_datasets(self, limit: int = 100) -> list[DatasetSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT dataset_id, original_filename, file_type, table_count, created_at
                FROM datasets
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            DatasetSummary(
                dataset_id=row["dataset_id"],
                original_filename=row["original_filename"],
                file_type=row["file_type"],
                table_count=row["table_count"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def save_history(
        self,
        dataset_id: str,
        question: str,
        generated_sql: str,
        result: dict[str, Any],
        chart: dict[str, Any] | None,
        insight: dict[str, Any] | None,
        correction_attempts: int,
    ) -> int:
        created_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO query_history (
                    dataset_id,
                    question,
                    generated_sql,
                    result_json,
                    chart_json,
                    insight_json,
                    correction_attempts,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    question,
                    generated_sql,
                    json.dumps(result),
                    json.dumps(chart) if chart is not None else None,
                    json.dumps(insight) if insight is not None else None,
                    correction_attempts,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def list_history(
        self,
        dataset_id: str,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT *
                FROM query_history
                WHERE dataset_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (dataset_id, limit),
            ).fetchall()

    def get_history_items(
        self,
        dataset_id: str,
        limit: int = 50,
    ) -> list[QueryHistoryItem]:
        rows = self.list_history(dataset_id, limit)
        return [
            QueryHistoryItem(
                history_id=row["history_id"],
                dataset_id=row["dataset_id"],
                question=row["question"],
                generated_sql=row["generated_sql"],
                result=SQLQueryResponse.model_validate_json(row["result_json"]),
                chart=(
                    ChartSpec.model_validate_json(row["chart_json"])
                    if row["chart_json"]
                    else None
                ),
                insight=(
                    BusinessInsight.model_validate_json(row["insight_json"])
                    if row["insight_json"]
                    else None
                ),
                correction_attempts=row["correction_attempts"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection
