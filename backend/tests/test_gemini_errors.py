from app.services.result_interpreter import GeminiResultInterpreter
from app.services.sql_generator import GeminiSQLGenerator


def test_sql_generator_reports_permission_denial():
    message = GeminiSQLGenerator._provider_error_message(
        RuntimeError("403 PERMISSION_DENIED")
    )

    assert "denied access" in message


def test_result_interpreter_reports_quota_error():
    message = GeminiResultInterpreter._provider_error_message(
        RuntimeError("429 RESOURCE_EXHAUSTED")
    )

    assert "quota is exhausted" in message
