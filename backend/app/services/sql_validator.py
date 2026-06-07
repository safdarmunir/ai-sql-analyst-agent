from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

EXTERNAL_READ_FUNCTIONS = {
    "csv_scan",
    "glob",
    "http_get",
    "mysql_scan",
    "parquet_scan",
    "postgres_scan",
    "read_blob",
    "read_csv",
    "read_csv_auto",
    "read_json",
    "read_json_auto",
    "read_ndjson",
    "read_parquet",
    "sqlite_scan",
}


class SQLValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedSQL:
    sql: str


class SQLValidator:
    def validate(self, sql: str, allowed_tables: set[str]) -> ValidatedSQL:
        candidate = sql.strip()
        if not candidate:
            raise SQLValidationError("SQL cannot be empty.")

        try:
            statements = [statement for statement in parse(candidate, read="duckdb") if statement]
        except ParseError as exc:
            raise SQLValidationError(f"SQL syntax is invalid: {exc}") from exc

        if len(statements) != 1:
            raise SQLValidationError("Exactly one SQL statement is allowed.")

        statement = statements[0]
        if not isinstance(statement, exp.Query) or statement.find(exp.Select) is None:
            raise SQLValidationError("Only SELECT or WITH queries are allowed.")

        cte_names = {
            cte.alias_or_name.casefold()
            for cte in statement.find_all(exp.CTE)
            if cte.alias_or_name
        }
        allowed_names = {name.casefold() for name in allowed_tables} | cte_names
        referenced_tables = {
            table.name.casefold()
            for table in statement.find_all(exp.Table)
            if table.name
        }
        unknown_tables = referenced_tables - allowed_names
        if unknown_tables:
            names = ", ".join(sorted(unknown_tables))
            raise SQLValidationError(f"Query references unavailable table(s): {names}.")

        table_functions = {
            self._function_name(table.this)
            for table in statement.find_all(exp.Table)
            if isinstance(table.this, exp.Func)
        }
        if table_functions:
            names = ", ".join(sorted(table_functions))
            raise SQLValidationError(
                f"Table-valued function(s) are not allowed: {names}."
            )

        external_functions = {
            self._function_name(function)
            for function in statement.find_all(exp.Func)
            if self._function_name(function) in EXTERNAL_READ_FUNCTIONS
        }
        if external_functions:
            names = ", ".join(sorted(external_functions))
            raise SQLValidationError(
                f"External data access function(s) are not allowed: {names}."
            )

        return ValidatedSQL(sql=statement.sql(dialect="duckdb"))

    @staticmethod
    def _function_name(function: exp.Func) -> str:
        if isinstance(function, exp.Anonymous):
            return function.name.casefold()
        return function.sql_name().casefold()
