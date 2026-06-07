from typing import Protocol

from google import genai
from google.genai import types
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, settings
from app.schemas.dataset import GeneratedSQL, TableSchema


class SQLGenerationError(RuntimeError):
    pass


class SQLGenerator(Protocol):
    async def generate(
        self,
        question: str,
        tables: list[TableSchema],
        previous_sql: str | None = None,
        error: str | None = None,
    ) -> GeneratedSQL: ...


class GeminiSQLGenerator:
    def __init__(self, app_settings: Settings) -> None:
        self.settings = app_settings

    async def generate(
        self,
        question: str,
        tables: list[TableSchema],
        previous_sql: str | None = None,
        error: str | None = None,
    ) -> GeneratedSQL:
        if not self.settings.gemini_api_key:
            raise SQLGenerationError("GEMINI_API_KEY is not configured.")

        prompt = self._build_prompt(question, tables, previous_sql, error)
        try:
            response = await run_in_threadpool(self._generate_content, prompt)
            if not response.text:
                raise SQLGenerationError("Gemini returned an empty response.")
            return GeneratedSQL.model_validate_json(response.text)
        except (ValidationError, ValueError) as exc:
            raise SQLGenerationError(
                "Gemini returned an invalid structured SQL response."
            ) from exc
        except SQLGenerationError:
            raise
        except Exception as exc:
            raise SQLGenerationError(self._provider_error_message(exc)) from exc

    def _generate_content(self, prompt: str):
        client = genai.Client(api_key=self.settings.gemini_api_key)
        return client.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=GeneratedSQL.model_json_schema(),
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
        return "Gemini SQL generation failed."

    @staticmethod
    def _build_prompt(
        question: str,
        tables: list[TableSchema],
        previous_sql: str | None,
        error: str | None,
    ) -> str:
        schema_text = "\n\n".join(
            (
                f"Table: {table.name}\n"
                f"Columns: "
                + ", ".join(
                    f"{column.name} ({column.data_type})"
                    for column in table.columns
                )
                + f"\nSample rows: {table.sample_rows}"
            )
            for table in tables
        )
        correction_context = ""
        if previous_sql and error:
            correction_context = (
                "\nA previous attempt failed. Correct it using the error below."
                f"\nPrevious SQL: {previous_sql}\nError: {error}\n"
            )

        return f"""
You are a senior analytics engineer generating DuckDB SQL.

Rules:
- Return exactly one SELECT query, optionally beginning with WITH.
- Use only the tables and columns in the provided schema.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, COPY, ATTACH,
  INSTALL, LOAD, PRAGMA, external files, URLs, or external scan functions.
- Do not invent tables or columns.
- Prefer clear aliases and deterministic ordering for ranked results.
- The application will enforce its own result row limit.

Schema:
{schema_text}

Business question:
{question}
{correction_context}
""".strip()


def get_sql_generator() -> GeminiSQLGenerator:
    return GeminiSQLGenerator(settings)
