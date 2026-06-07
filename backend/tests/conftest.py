import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.db.metadata_repository import MetadataRepository
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    MetadataRepository(settings.metadata_database_path).initialize()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
