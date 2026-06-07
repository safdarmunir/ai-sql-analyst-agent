import os
from dataclasses import dataclass
from pathlib import Path


def _resolve_data_dir() -> Path:
    configured_path = Path(os.getenv("APP_DATA_DIR", "./data"))
    return configured_path.resolve()


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "AI SQL Analyst Agent")
    api_v1_prefix: str = "/api/v1"
    data_dir: Path = _resolve_data_dir()
    max_upload_size_mb: int = int(os.getenv("APP_MAX_UPLOAD_SIZE_MB", "25"))
    schema_sample_rows: int = int(os.getenv("APP_SCHEMA_SAMPLE_ROWS", "5"))
    max_query_rows: int = int(os.getenv("APP_MAX_QUERY_ROWS", "1000"))
    sql_correction_attempts: int = int(
        os.getenv("APP_SQL_CORRECTION_ATTEMPTS", "1")
    )
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:8501")

    @property
    def datasets_dir(self) -> Path:
        return self.data_dir / "datasets"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def metadata_database_path(self) -> Path:
        return self.data_dir / "metadata.sqlite3"

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


settings = Settings()
