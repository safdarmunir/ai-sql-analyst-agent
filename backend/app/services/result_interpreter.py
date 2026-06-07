from typing import Protocol

from google import genai
from google.genai import types
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, settings
from app.schemas.dataset import (
    BusinessInsight,
    ChartSpec,
    ResultInterpretation,
    SQLQueryResponse,
)


class ResultInterpretationError(RuntimeError):
    pass


class ResultInterpreter(Protocol):
    async def interpret(
        self,
        question: str,
        sql: str,
        result: SQLQueryResponse,
    ) -> ResultInterpretation: ...


class GeminiResultInterpreter:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings

    async def interpret(
        self,
        question: str,
        sql: str,
        result: SQLQueryResponse,
    ) -> ResultInterpretation:
        if not self.settings.gemini_api_key:
            raise ResultInterpretationError("GEMINI_API_KEY is not configured.")

        prompt = self._build_prompt(question, sql, result)
        try:
            response = await run_in_threadpool(self._generate_content, prompt)
            if not response.text:
                raise ResultInterpretationError("Gemini returned an empty response.")
            interpretation = ResultInterpretation.model_validate_json(response.text)
            return self._sanitize_chart(interpretation, result.columns)
        except (ValidationError, ValueError) as exc:
            raise ResultInterpretationError(
                "Gemini returned an invalid interpretation response."
            ) from exc
        except ResultInterpretationError:
            raise
        except Exception as exc:
            raise ResultInterpretationError(
                self._provider_error_message(exc)
            ) from exc

    def _generate_content(self, prompt: str):
        client = genai.Client(api_key=self.settings.gemini_api_key)
        return client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
                response_json_schema=ResultInterpretation.model_json_schema(),
            ),
        )

    @staticmethod
    def _provider_error_message(exc: Exception) -> str:
        message = str(exc)
        if "PERMISSION_DENIED" in message:
            return (
                "Gemini denied access for this API key's Google project. "
                "Use a key from a project with Gemini API access enabled."
            )
        if "RESOURCE_EXHAUSTED" in message:
            return "Gemini quota is exhausted. Check the project's quota or billing."
        if "API_KEY_INVALID" in message or "API key not valid" in message:
            return "The configured Gemini API key is invalid."
        return "Gemini result interpretation failed."

    @staticmethod
    def _build_prompt(
        question: str,
        sql: str,
        result: SQLQueryResponse,
    ) -> str:
        preview = result.rows[:100]
        return f"""
You are a business data analyst.

Using the question, SQL, and result preview:
1. Explain the answer in concise business language.
2. Give up to five evidence-based key points.
3. Mention caveats such as truncation, small samples, or missing context.
4. Recommend a chart only when it improves understanding.

Chart rules:
- Use only columns listed below.
- Use "none" for one-value results or when a chart adds little value.
- Use line for ordered time trends, bar for category comparisons,
  pie only for a small part-to-whole result, and scatter for two numeric measures.
- Select one x column and one or more numeric y columns.

Question: {question}
SQL: {sql}
Columns: {result.columns}
Rows returned: {result.row_count}
Result truncated: {result.truncated}
Result preview: {preview}
""".strip()

    @staticmethod
    def _sanitize_chart(
        interpretation: ResultInterpretation,
        columns: list[str],
    ) -> ResultInterpretation:
        available = set(columns)
        chart = interpretation.chart
        valid_y_columns = [column for column in chart.y_columns if column in available]
        if (
            chart.chart_type == "none"
            or chart.x_column not in available
            or not valid_y_columns
        ):
            chart = ChartSpec(
                chart_type="none",
                title=chart.title,
                reason=chart.reason or "The result is better presented as a table.",
            )
        else:
            chart = chart.model_copy(update={"y_columns": valid_y_columns})
        return interpretation.model_copy(update={"chart": chart})


class FallbackResultInterpreter:
    async def interpret(
        self,
        question: str,
        sql: str,
        result: SQLQueryResponse,
    ) -> ResultInterpretation:
        summary = (
            f"The query returned {result.row_count} row"
            f"{'' if result.row_count == 1 else 's'}."
        )
        caveats = ["The result was capped by the row limit."] if result.truncated else []
        return ResultInterpretation(
            chart=ChartSpec(
                chart_type="none",
                reason="Automatic interpretation is unavailable without Gemini.",
            ),
            insight=BusinessInsight(
                summary=summary,
                key_points=[],
                caveats=caveats,
            ),
        )


def get_result_interpreter() -> ResultInterpreter:
    if settings.gemini_api_key:
        return GeminiResultInterpreter(settings)
    return FallbackResultInterpreter()
