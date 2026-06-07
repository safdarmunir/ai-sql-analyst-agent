import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from app.schemas.dataset import (
    ColumnProfile,
    ColumnSchema,
    SQLQueryResponse,
    TableProfile,
    TableSchema,
)


NUMERIC_TYPES = {
    "BIGINT",
    "DECIMAL",
    "DOUBLE",
    "FLOAT",
    "HUGEINT",
    "INTEGER",
    "REAL",
    "SMALLINT",
    "TINYINT",
    "UBIGINT",
    "UHUGEINT",
    "UINTEGER",
    "USMALLINT",
    "UTINYINT",
}
DATE_TYPES = {"DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE"}


def quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


class DuckDBRepository:
    def import_csv(
        self,
        database_path: Path,
        csv_path: Path,
        table_name: str,
        sample_rows: int,
    ) -> TableSchema:
        quoted_table = quote_identifier(table_name)

        with duckdb.connect(str(database_path)) as connection:
            connection.execute(
                f"""
                CREATE TABLE {quoted_table} AS
                SELECT *
                FROM read_csv(?, header = true, auto_detect = true)
                """,
                [str(csv_path)],
            )

            row_count = connection.execute(
                f"SELECT COUNT(*) FROM {quoted_table}"
            ).fetchone()[0]
            column_rows = connection.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = ?
                ORDER BY ordinal_position
                """,
                [table_name],
            ).fetchall()
            sample_result = connection.execute(
                f"SELECT * FROM {quoted_table} LIMIT ?",
                [sample_rows],
            )
            sample_columns = [item[0] for item in sample_result.description]
            sample_data = [
                dict(zip(sample_columns, row, strict=True))
                for row in sample_result.fetchall()
            ]

        columns = [
            ColumnSchema(
                name=name,
                data_type=data_type,
                nullable=is_nullable == "YES",
            )
            for name, data_type, is_nullable in column_rows
        ]
        return TableSchema(
            name=table_name,
            row_count=row_count,
            columns=columns,
            sample_rows=[self._json_safe_row(row) for row in sample_data],
        )

    def import_dataframes(
        self,
        database_path: Path,
        dataframes: dict[str, pd.DataFrame],
        sample_rows: int,
    ) -> list[TableSchema]:
        with duckdb.connect(str(database_path)) as connection:
            for index, (table_name, dataframe) in enumerate(dataframes.items()):
                registered_name = f"_upload_{index}"
                connection.register(registered_name, dataframe)
                try:
                    connection.execute(
                        f"""
                        CREATE TABLE {quote_identifier(table_name)} AS
                        SELECT * FROM {quote_identifier(registered_name)}
                        """
                    )
                finally:
                    connection.unregister(registered_name)

            return [
                self._get_table_schema(connection, table_name, sample_rows)
                for table_name in dataframes
            ]

    def get_schema(self, database_path: Path, sample_rows: int) -> list[TableSchema]:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            table_names = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """
                ).fetchall()
            ]
            return [
                self._get_table_schema(connection, table_name, sample_rows)
                for table_name in table_names
            ]

    def execute_query(
        self,
        database_path: Path,
        sql: str,
        max_rows: int,
    ) -> SQLQueryResponse:
        limited_sql = f"SELECT * FROM ({sql}) AS _query_result LIMIT {max_rows + 1}"
        started_at = time.perf_counter()

        with duckdb.connect(str(database_path), read_only=True) as connection:
            result = connection.execute(limited_sql)
            columns = [item[0] for item in result.description]
            raw_rows = result.fetchall()

        execution_time_ms = (time.perf_counter() - started_at) * 1000
        truncated = len(raw_rows) > max_rows
        raw_rows = raw_rows[:max_rows]
        rows = [
            self._json_safe_row(dict(zip(columns, row, strict=True)))
            for row in raw_rows
        ]
        return SQLQueryResponse(
            sql=sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            execution_time_ms=round(execution_time_ms, 3),
        )

    def get_table_profiles(self, database_path: Path) -> list[TableProfile]:
        with duckdb.connect(str(database_path), read_only=True) as connection:
            table_names = [
                row[0]
                for row in connection.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                    """
                ).fetchall()
            ]
            return [
                self._get_table_profile(connection, table_name)
                for table_name in table_names
            ]

    def _get_table_schema(
        self,
        connection: duckdb.DuckDBPyConnection,
        table_name: str,
        sample_rows: int,
    ) -> TableSchema:
        quoted_table = quote_identifier(table_name)
        row_count = connection.execute(
            f"SELECT COUNT(*) FROM {quoted_table}"
        ).fetchone()[0]
        column_rows = connection.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = ?
            ORDER BY ordinal_position
            """,
            [table_name],
        ).fetchall()
        sample_result = connection.execute(
            f"SELECT * FROM {quoted_table} LIMIT ?",
            [sample_rows],
        )
        sample_columns = [item[0] for item in sample_result.description]
        sample_data = [
            dict(zip(sample_columns, row, strict=True))
            for row in sample_result.fetchall()
        ]
        return TableSchema(
            name=table_name,
            row_count=row_count,
            columns=[
                ColumnSchema(
                    name=name,
                    data_type=data_type,
                    nullable=is_nullable == "YES",
                )
                for name, data_type, is_nullable in column_rows
            ],
            sample_rows=[self._json_safe_row(row) for row in sample_data],
        )

    def _get_table_profile(
        self,
        connection: duckdb.DuckDBPyConnection,
        table_name: str,
    ) -> TableProfile:
        quoted_table = quote_identifier(table_name)
        row_count = connection.execute(
            f"SELECT COUNT(*) FROM {quoted_table}"
        ).fetchone()[0]
        column_rows = connection.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = ?
            ORDER BY ordinal_position
            """,
            [table_name],
        ).fetchall()

        profiles = []
        for column_name, data_type in column_rows:
            quoted_column = quote_identifier(column_name)
            include_range = (
                data_type.upper() in NUMERIC_TYPES
                or any(data_type.upper().startswith(item) for item in DATE_TYPES)
            )
            range_sql = (
                f", MIN({quoted_column}), MAX({quoted_column})"
                if include_range
                else ""
            )
            values = connection.execute(
                f"""
                SELECT
                    COUNT(DISTINCT {quoted_column}),
                    COUNT(*) FILTER (WHERE {quoted_column} IS NULL)
                    {range_sql}
                FROM {quoted_table}
                """
            ).fetchone()
            minimum = values[2] if include_range else None
            maximum = values[3] if include_range else None
            profiles.append(
                ColumnProfile(
                    name=column_name,
                    data_type=data_type,
                    semantic_role="other",
                    distinct_count=values[0],
                    null_count=values[1],
                    minimum=self._json_safe_value(minimum),
                    maximum=self._json_safe_value(maximum),
                )
            )

        return TableProfile(
            name=table_name,
            row_count=row_count,
            columns=profiles,
        )

    @staticmethod
    def _json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: DuckDBRepository._json_safe_value(value)
            for key, value in row.items()
        }

    @staticmethod
    def _json_safe_value(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        return value
