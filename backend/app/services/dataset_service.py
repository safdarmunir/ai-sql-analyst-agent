import logging
import re
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

import pandas as pd
from fastapi import HTTPException, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, settings
from app.db.duckdb_repository import DuckDBRepository
from app.db.metadata_repository import MetadataRepository
from app.schemas.dataset import DatasetListResponse, DatasetUploadResponse

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".sqlite", ".sqlite3", ".db"}
SUPPORTED_CONTENT_TYPES = {
    "application/csv",
    "application/octet-stream",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/x-sqlite3",
    "application/vnd.sqlite3",
    "text/csv",
    "text/plain",
}
UPLOAD_CHUNK_SIZE = 1024 * 1024
logger = logging.getLogger(__name__)


class DatasetService:
    def __init__(
        self,
        app_settings: Settings,
        repository: DuckDBRepository,
        metadata_repository: MetadataRepository,
    ) -> None:
        self.settings = app_settings
        self.repository = repository
        self.metadata_repository = metadata_repository

    async def create_from_upload(self, upload: UploadFile) -> DatasetUploadResponse:
        original_filename = Path(upload.filename or "").name
        if not original_filename:
            self._raise_bad_request("A filename is required.")
        extension = Path(original_filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            self._raise_bad_request(
                "Supported file types are CSV, XLSX, SQLite, SQLite3, and DB."
            )
        if upload.content_type and upload.content_type not in SUPPORTED_CONTENT_TYPES:
            self._raise_bad_request("The uploaded file type is not supported.")

        dataset_id = str(uuid4())
        database_path = self.settings.datasets_dir / f"{dataset_id}.duckdb"
        self.settings.datasets_dir.mkdir(parents=True, exist_ok=True)

        temp_path: Path | None = None
        try:
            temp_path = await self._save_to_temporary_file(upload, extension)
            tables = await run_in_threadpool(
                self._import_file,
                database_path,
                temp_path,
                original_filename,
                extension,
            )
            await run_in_threadpool(
                self.metadata_repository.save_dataset,
                dataset_id,
                original_filename,
                extension.lstrip("."),
                database_path.name,
                len(tables),
            )
        except HTTPException:
            raise
        except Exception as exc:
            database_path.unlink(missing_ok=True)
            logger.exception("Dataset import failed for dataset %s", dataset_id)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Could not import the file. Check its structure and encoding.",
            ) from exc
        finally:
            await upload.close()
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        return DatasetUploadResponse(
            dataset_id=dataset_id,
            original_filename=original_filename,
            database_filename=database_path.name,
            file_type=extension.lstrip("."),
            tables=tables,
            table=tables[0] if tables else None,
        )

    async def list_datasets(self) -> DatasetListResponse:
        datasets = await run_in_threadpool(self.metadata_repository.list_datasets)
        return DatasetListResponse(datasets=datasets)

    def _import_file(
        self,
        database_path: Path,
        source_path: Path,
        original_filename: str,
        extension: str,
    ):
        if extension == ".csv":
            return [
                self.repository.import_csv(
                    database_path,
                    source_path,
                    self._table_name_from_filename(original_filename),
                    self.settings.schema_sample_rows,
                )
            ]
        if extension == ".xlsx":
            frames = pd.read_excel(source_path, sheet_name=None, engine="openpyxl")
            dataframes = self._normalize_dataframes(frames)
        else:
            dataframes = self._read_sqlite_tables(source_path)

        if not dataframes:
            raise ValueError("The uploaded file contains no readable tables.")
        return self.repository.import_dataframes(
            database_path,
            dataframes,
            self.settings.schema_sample_rows,
        )

    def _read_sqlite_tables(self, source_path: Path) -> dict[str, pd.DataFrame]:
        connection = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        try:
            table_names = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                    """
                ).fetchall()
            ]
            frames = {
                table_name: pd.read_sql_query(
                    f"SELECT * FROM {self._quote_sqlite_identifier(table_name)}",
                    connection,
                )
                for table_name in table_names
            }
        finally:
            connection.close()
        return self._normalize_dataframes(frames)

    def _normalize_dataframes(
        self,
        frames: dict[str, pd.DataFrame],
    ) -> dict[str, pd.DataFrame]:
        normalized: dict[str, pd.DataFrame] = {}
        used_names: set[str] = set()
        for source_name, dataframe in frames.items():
            base_name = self._normalize_table_name(source_name)
            table_name = base_name
            suffix = 2
            while table_name in used_names:
                table_name = f"{base_name[:58]}_{suffix}"
                suffix += 1
            used_names.add(table_name)
            normalized[table_name] = dataframe
        return normalized

    async def _save_to_temporary_file(
        self,
        upload: UploadFile,
        extension: str,
    ) -> Path:
        total_bytes = 0
        exceeds_size_limit = False
        with NamedTemporaryFile(delete=False, suffix=extension) as temporary_file:
            temp_path = Path(temporary_file.name)
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > self.settings.max_upload_size_bytes:
                    exceeds_size_limit = True
                    break
                temporary_file.write(chunk)

        if exceeds_size_limit:
            temp_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    "File exceeds the "
                    f"{self.settings.max_upload_size_mb} MB upload limit."
                ),
            )
        if total_bytes == 0:
            temp_path.unlink(missing_ok=True)
            self._raise_bad_request("The uploaded CSV is empty.")
        return temp_path

    @staticmethod
    def _table_name_from_filename(filename: str) -> str:
        return DatasetService._normalize_table_name(Path(filename).stem)

    @staticmethod
    def _normalize_table_name(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value)
        normalized = normalized.strip("_").lower() or "uploaded_data"
        if normalized[0].isdigit():
            normalized = f"data_{normalized}"
        return normalized[:63]

    @staticmethod
    def _quote_sqlite_identifier(identifier: str) -> str:
        return f'"{identifier.replace(chr(34), chr(34) * 2)}"'

    @staticmethod
    def _raise_bad_request(message: str) -> None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )


def get_dataset_service() -> DatasetService:
    metadata_repository = MetadataRepository(settings.metadata_database_path)
    metadata_repository.initialize()
    return DatasetService(
        app_settings=settings,
        repository=DuckDBRepository(),
        metadata_repository=metadata_repository,
    )
