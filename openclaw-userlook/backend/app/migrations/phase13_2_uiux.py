from __future__ import annotations

from sqlalchemy import text

from app.core.database import engine


def _current_database(connection) -> str:
    return connection.execute(text("SELECT DATABASE()")).scalar_one()


def _column_exists(connection, database_name: str, table_name: str, column_name: str) -> bool:
    return (
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = :database_name
                  AND TABLE_NAME = :table_name
                  AND COLUMN_NAME = :column_name
                """
            ),
            {
                "database_name": database_name,
                "table_name": table_name,
                "column_name": column_name,
            },
        ).scalar_one()
        > 0
    )


def _add_column(connection, database_name: str, table_name: str, column_name: str, definition: str) -> None:
    if not _column_exists(connection, database_name, table_name, column_name):
        connection.execute(text(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition}"))


def run_migration() -> None:
    with engine.begin() as connection:
        database_name = _current_database(connection)
        _add_column(
            connection,
            database_name,
            "conversations",
            "is_title_manual",
            "BOOLEAN NOT NULL DEFAULT FALSE",
        )


if __name__ == "__main__":
    run_migration()
    print("Phase 13.2 UI/UX migration completed.")
