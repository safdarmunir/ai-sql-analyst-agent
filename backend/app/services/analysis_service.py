from typing import TypedDict

from fastapi import Depends, HTTPException, status
from langgraph.graph import END, START, StateGraph
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, settings
from app.db.metadata_repository import MetadataRepository
from app.schemas.dataset import (
    AnalysisResponse,
    BusinessInsight,
    ChartSpec,
    SQLQueryResponse,
    TableSchema,
)
from app.services.query_service import QueryService, get_query_service
from app.services.result_interpreter import (
    FallbackResultInterpreter,
    ResultInterpretationError,
    ResultInterpreter,
    get_result_interpreter,
)
from app.services.sql_generator import (
    SQLGenerationError,
    SQLGenerator,
    get_sql_generator,
)


class AnalysisState(TypedDict, total=False):
    dataset_id: str
    question: str
    tables: list[TableSchema]
    generated_sql: str
    result: SQLQueryResponse
    chart: ChartSpec
    insight: BusinessInsight
    attempts: int
    error: str
    history_id: int


class AnalysisService:
    def __init__(
        self,
        app_settings: Settings,
        query_service: QueryService,
        sql_generator: SQLGenerator,
        result_interpreter: ResultInterpreter,
        metadata_repository: MetadataRepository,
    ) -> None:
        self.settings = app_settings
        self.query_service = query_service
        self.sql_generator = sql_generator
        self.result_interpreter = result_interpreter
        self.metadata_repository = metadata_repository
        self.graph = self._build_graph()

    async def analyze(self, dataset_id: str, question: str) -> AnalysisResponse:
        final_state = await self.graph.ainvoke(
            {
                "dataset_id": dataset_id,
                "question": question,
                "attempts": 0,
            }
        )
        return AnalysisResponse(
            question=question,
            generated_sql=final_state["generated_sql"],
            result=final_state["result"],
            chart=final_state["chart"],
            insight=final_state["insight"],
            correction_attempts=final_state["attempts"],
            history_id=final_state.get("history_id"),
        )

    def _build_graph(self):
        graph = StateGraph(AnalysisState)
        graph.add_node("schema_reader", self._read_schema)
        graph.add_node("sql_generator", self._generate_sql)
        graph.add_node("sql_executor", self._execute_sql)
        graph.add_node("result_interpreter", self._interpret_result)
        graph.add_node("history_writer", self._write_history)
        graph.add_node("failure", self._raise_failure)

        graph.add_edge(START, "schema_reader")
        graph.add_edge("schema_reader", "sql_generator")
        graph.add_edge("sql_generator", "sql_executor")
        graph.add_conditional_edges(
            "sql_executor",
            self._route_after_execution,
            {
                "correct": "sql_generator",
                "interpret": "result_interpreter",
                "fail": "failure",
            },
        )
        graph.add_edge("result_interpreter", "history_writer")
        graph.add_edge("history_writer", END)
        return graph.compile()

    async def _read_schema(self, state: AnalysisState) -> dict:
        schema = await self.query_service.get_schema(state["dataset_id"])
        return {"tables": schema.tables}

    async def _generate_sql(self, state: AnalysisState) -> dict:
        try:
            generated = await self.sql_generator.generate(
                question=state["question"],
                tables=state["tables"],
                previous_sql=state.get("generated_sql"),
                error=state.get("error"),
            )
        except SQLGenerationError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
        return {"generated_sql": generated.sql, "error": ""}

    async def _execute_sql(self, state: AnalysisState) -> dict:
        try:
            result = await self.query_service.execute(
                state["dataset_id"],
                state["generated_sql"],
            )
            return {"result": result, "error": ""}
        except HTTPException as exc:
            if exc.status_code not in {
                status.HTTP_400_BAD_REQUEST,
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            }:
                raise
            return {
                "error": str(exc.detail),
                "attempts": state.get("attempts", 0) + 1,
            }

    def _route_after_execution(self, state: AnalysisState) -> str:
        if state.get("result") is not None and not state.get("error"):
            return "interpret"
        if state.get("attempts", 0) <= self.settings.sql_correction_attempts:
            return "correct"
        return "fail"

    async def _interpret_result(self, state: AnalysisState) -> dict:
        try:
            interpretation = await self.result_interpreter.interpret(
                question=state["question"],
                sql=state["result"].sql,
                result=state["result"],
            )
        except ResultInterpretationError as exc:
            interpretation = await FallbackResultInterpreter().interpret(
                question=state["question"],
                sql=state["result"].sql,
                result=state["result"],
            )
            interpretation.insight.caveats.append(str(exc))
        return {
            "chart": interpretation.chart,
            "insight": interpretation.insight,
        }

    async def _write_history(self, state: AnalysisState) -> dict:
        history_id = await run_in_threadpool(
            self.metadata_repository.save_history,
            state["dataset_id"],
            state["question"],
            state["result"].sql,
            state["result"].model_dump(mode="json"),
            state["chart"].model_dump(mode="json"),
            state["insight"].model_dump(mode="json"),
            state.get("attempts", 0),
        )
        return {"history_id": history_id}

    async def _raise_failure(self, state: AnalysisState) -> dict:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Generated SQL failed validation or execution.",
                "sql": state.get("generated_sql"),
                "error": state.get("error"),
            },
        )


def get_analysis_service(
    query_service: QueryService = Depends(get_query_service),
    sql_generator: SQLGenerator = Depends(get_sql_generator),
    result_interpreter: ResultInterpreter = Depends(get_result_interpreter),
) -> AnalysisService:
    metadata_repository = MetadataRepository(settings.metadata_database_path)
    metadata_repository.initialize()
    return AnalysisService(
        app_settings=settings,
        query_service=query_service,
        sql_generator=sql_generator,
        result_interpreter=result_interpreter,
        metadata_repository=metadata_repository,
    )
