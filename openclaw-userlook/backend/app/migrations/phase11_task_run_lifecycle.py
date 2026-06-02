from __future__ import annotations

from sqlalchemy import text

from app.core.database import engine


TASK_RUN_STATUS_ENUM = (
    "ENUM('pending','queued','running','success','failed','cancelled','timeout','stale') "
    "NOT NULL DEFAULT 'queued'"
)


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


def _constraint_exists(connection, database_name: str, table_name: str, constraint_name: str) -> bool:
    return (
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.TABLE_CONSTRAINTS
                WHERE TABLE_SCHEMA = :database_name
                  AND TABLE_NAME = :table_name
                  AND CONSTRAINT_NAME = :constraint_name
                """
            ),
            {
                "database_name": database_name,
                "table_name": table_name,
                "constraint_name": constraint_name,
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

        connection.execute(text(f"ALTER TABLE `task_runs` MODIFY COLUMN `status` {TASK_RUN_STATUS_ENUM}"))
        _add_column(connection, database_name, "task_runs", "run_type", "VARCHAR(50) NOT NULL DEFAULT 'chat'")
        _add_column(connection, database_name, "task_runs", "priority", "INT NOT NULL DEFAULT 100")
        _add_column(connection, database_name, "task_runs", "queued_at", "DATETIME(6) NULL")
        _add_column(connection, database_name, "task_runs", "heartbeat_at", "DATETIME(6) NULL")
        _add_column(
            connection,
            database_name,
            "task_runs",
            "cancel_requested",
            "TINYINT(1) NOT NULL DEFAULT 0",
        )
        _add_column(connection, database_name, "task_runs", "output_files_json", "JSON NULL")
        _add_column(connection, database_name, "task_runs", "timeout_seconds", "INT NULL")

        _add_column(connection, database_name, "messages", "run_id", "BIGINT NULL")
        if not _index_exists(connection, database_name, "messages", "ix_messages_run_id"):
            connection.execute(text("CREATE INDEX `ix_messages_run_id` ON `messages` (`run_id`)"))
        if not _constraint_exists(connection, database_name, "messages", "fk_messages_run_id_task_runs"):
            connection.execute(
                text(
                    """
                    ALTER TABLE `messages`
                    ADD CONSTRAINT `fk_messages_run_id_task_runs`
                    FOREIGN KEY (`run_id`) REFERENCES `task_runs` (`id`)
                    ON DELETE SET NULL
                    """
                )
            )


if __name__ == "__main__":
    run_migration()
    print("Phase 11 task run lifecycle migration completed.")
