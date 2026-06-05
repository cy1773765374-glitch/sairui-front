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


def _create_index(connection, database_name: str, table_name: str, index_name: str, definition: str) -> None:
    if not _index_exists(connection, database_name, table_name, index_name):
        connection.execute(text(f"CREATE INDEX `{index_name}` ON `{table_name}` {definition}"))


def run_migration() -> None:
    with engine.begin() as connection:
        database_name = _current_database(connection)

        _add_column(connection, database_name, "files", "conversation_id", "BIGINT NULL")
        _add_column(connection, database_name, "files", "agent_code", "VARCHAR(64) NULL")
        _add_column(connection, database_name, "files", "stored_name", "VARCHAR(255) NULL")
        _add_column(connection, database_name, "files", "workspace_path", "VARCHAR(500) NULL")
        _add_column(connection, database_name, "files", "sha256", "VARCHAR(64) NULL")
        _add_column(connection, database_name, "files", "status", "VARCHAR(50) NOT NULL DEFAULT 'ready'")
        _add_column(
            connection,
            database_name,
            "files",
            "updated_at",
            "DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)",
        )

        connection.execute(text("UPDATE `files` SET `status` = 'ready' WHERE `status` IS NULL OR `status` = ''"))
        connection.execute(text("UPDATE `files` SET `stored_name` = SUBSTRING_INDEX(`stored_path`, '/', -1) WHERE `stored_name` IS NULL"))

        _create_index(connection, database_name, "files", "ix_files_conversation_id", "(`conversation_id`)")
        _create_index(connection, database_name, "files", "ix_files_agent_code", "(`agent_code`)")


if __name__ == "__main__":
    run_migration()
    print("Phase 13.4 daoban file chain migration completed.")
