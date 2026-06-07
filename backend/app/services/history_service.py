from fastapi import HTTPException, status
from starlette.concurrency import run_in_threadpool
from uuid import UUID

from app.core.config import Settings, settings
from app.db.metadata_repository import MetadataRepository
from app.schemas.dataset import QueryHistoryResponse


class HistoryService:
    def __init__(
        self,
        app_settings: Settings,
        repository: MetadataRepository,
    ) -> None:
        self.settings = app_settings
        self.repository = repository

    async def list_history(
        self,
        dataset_id: str,
        limit: int,
    ) -> QueryHistoryResponse:
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
        items = await run_in_threadpool(
            self.repository.get_history_items,
            normalized_id,
            limit,
        )
        return QueryHistoryResponse(items=items)


def get_history_service() -> HistoryService:
    repository = MetadataRepository(settings.metadata_database_path)
    repository.initialize()
    return HistoryService(
        app_settings=settings,
        repository=repository,
    )
