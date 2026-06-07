from fastapi import APIRouter, Depends, File, UploadFile, status

from app.schemas.dataset import (
    AnalysisResponse,
    DatasetDashboardResponse,
    DatasetSchemaResponse,
    DatasetListResponse,
    DatasetUploadResponse,
    NaturalLanguageQueryRequest,
    QueryHistoryResponse,
    SQLQueryRequest,
    SQLQueryResponse,
)
from app.services.analysis_service import AnalysisService, get_analysis_service
from app.services.dashboard_service import DashboardService, get_dashboard_service
from app.services.dataset_service import DatasetService, get_dataset_service
from app.services.history_service import HistoryService, get_history_service
from app.services.query_service import QueryService, get_query_service

router = APIRouter()


@router.get(
    "",
    response_model=DatasetListResponse,
    summary="List uploaded datasets",
)
async def list_datasets(
    service: DatasetService = Depends(get_dataset_service),
) -> DatasetListResponse:
    return await service.list_datasets()


@router.post(
    "/upload",
    response_model=DatasetUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV file and create a DuckDB dataset",
)
async def upload_dataset(
    file: UploadFile = File(..., description="CSV file to import"),
    service: DatasetService = Depends(get_dataset_service),
) -> DatasetUploadResponse:
    return await service.create_from_upload(file)


@router.get(
    "/{dataset_id}/schema",
    response_model=DatasetSchemaResponse,
    summary="Get the schema and sample rows for a dataset",
)
async def get_dataset_schema(
    dataset_id: str,
    service: QueryService = Depends(get_query_service),
) -> DatasetSchemaResponse:
    return await service.get_schema(dataset_id)


@router.get(
    "/{dataset_id}/dashboard",
    response_model=DatasetDashboardResponse,
    summary="Build an automatic dashboard from dataset semantics",
)
async def get_dataset_dashboard(
    dataset_id: str,
    service: DashboardService = Depends(get_dashboard_service),
) -> DatasetDashboardResponse:
    return await service.build_dashboard(dataset_id)


@router.post(
    "/{dataset_id}/query",
    response_model=SQLQueryResponse,
    summary="Validate and execute a read-only SQL query",
)
async def execute_dataset_query(
    dataset_id: str,
    request: SQLQueryRequest,
    service: QueryService = Depends(get_query_service),
) -> SQLQueryResponse:
    return await service.execute(dataset_id, request.sql)


@router.post(
    "/{dataset_id}/analyze",
    response_model=AnalysisResponse,
    summary="Generate safe SQL from a business question and execute it",
)
async def analyze_dataset(
    dataset_id: str,
    request: NaturalLanguageQueryRequest,
    service: AnalysisService = Depends(get_analysis_service),
) -> AnalysisResponse:
    return await service.analyze(dataset_id, request.question)


@router.get(
    "/{dataset_id}/history",
    response_model=QueryHistoryResponse,
    summary="List saved analysis history for a dataset",
)
async def get_dataset_history(
    dataset_id: str,
    limit: int = 50,
    service: HistoryService = Depends(get_history_service),
) -> QueryHistoryResponse:
    safe_limit = min(max(limit, 1), 100)
    return await service.list_history(dataset_id, safe_limit)
