import logging
from pathlib import Path
from uuid import UUID

import duckdb
from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, settings
from app.db.duckdb_repository import DuckDBRepository
from app.schemas.dataset import DatasetSchemaResponse, SQLQueryResponse, TableProfile
from app.services.sql_validator import SQLValidationError, SQLValidator

logger = logging.getLogger(__name__)


class QueryService:
    def __init__(
        self,
        app_settings: Settings,
        repository: DuckDBRepository,
        validator: SQLValidator,
    ) -> None:
        self.settings = app_settings
        self.repository = repository
        self.validator = validator

    async def get_schema(self, dataset_id: str) -> DatasetSchemaResponse:
        database_path = self._database_path(dataset_id)
        tables = await run_in_threadpool(
            self.repository.get_schema,
            database_path,
            self.settings.schema_sample_rows,
        )
        return DatasetSchemaResponse(dataset_id=dataset_id, tables=tables)

    async def execute(self, dataset_id: str, sql: str) -> SQLQueryResponse:
        database_path = self._database_path(dataset_id)
        tables = await run_in_threadpool(
            self.repository.get_schema,
            database_path,
            0,
        )

        try:
            validated = self.validator.validate(
                sql,
                allowed_tables={table.name for table in tables},
            )
        except SQLValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        try:
            return await run_in_threadpool(
                self.repository.execute_query,
                database_path,
                validated.sql,
                self.settings.max_query_rows,
            )
        except duckdb.Error as exc:
            logger.info("Query execution failed for dataset %s: %s", dataset_id, exc)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"SQL execution failed: {exc}",
            ) from exc

    async def get_profiles(self, dataset_id: str) -> list[TableProfile]:
        database_path = self._database_path(dataset_id)
        return await run_in_threadpool(
            self.repository.get_table_profiles,
            database_path,
        )

    def _database_path(self, dataset_id: str) -> Path:
        try:
            normalized_id = str(UUID(dataset_id))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found.",
            ) from exc

        database_path = self.settings.datasets_dir / f"{normalized_id}.duckdb"
        if not database_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found.",
            )
        return database_path


def get_query_service() -> QueryService:
    return QueryService(
        app_settings=settings,
        repository=DuckDBRepository(),
        validator=SQLValidator(),
    )
