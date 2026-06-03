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


def run_migration() -> None:
    with engine.begin() as connection:
        database_name = _current_database(connection)
        if not _column_exists(connection, database_name, "task_runs", "raw_payload"):
            connection.execute(text("ALTER TABLE `task_runs` ADD COLUMN `raw_payload` JSON NULL"))


if __name__ == "__main__":
    run_migration()
    print("Phase 12 streaming persistence migration completed.")
