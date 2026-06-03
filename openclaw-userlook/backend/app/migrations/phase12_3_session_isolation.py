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


def _index_exists(connection, database_name: str, table_name: str, index_name: str) -> bool:
    return (
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = :database_name
                  AND TABLE_NAME = :table_name
                  AND INDEX_NAME = :index_name
                """
            ),
            {
                "database_name": database_name,
                "table_name": table_name,
                "index_name": index_name,
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
        _add_column(connection, database_name, "task_runs", "client_message_id", "VARCHAR(80) NULL")
        _add_column(connection, database_name, "task_runs", "gateway_session_key", "VARCHAR(255) NULL")
        _add_column(connection, database_name, "task_runs", "idempotency_key", "VARCHAR(255) NULL")

        if not _index_exists(connection, database_name, "task_runs", "idx_task_runs_conversation_client_message"):
            connection.execute(
                text(
                    """
                    CREATE INDEX `idx_task_runs_conversation_client_message`
                    ON `task_runs` (`conversation_id`, `client_message_id`)
                    """
                )
            )
        if not _index_exists(connection, database_name, "task_runs", "uq_task_runs_conversation_client_message"):
            connection.execute(
                text(
                    """
                    CREATE UNIQUE INDEX `uq_task_runs_conversation_client_message`
                    ON `task_runs` (`conversation_id`, `client_message_id`)
                    """
                )
            )


if __name__ == "__main__":
    run_migration()
    print("Phase 12.3 session isolation migration completed.")
