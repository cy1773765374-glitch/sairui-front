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


def _table_exists(connection, database_name: str, table_name: str) -> bool:
    return (
        connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = :database_name
                  AND TABLE_NAME = :table_name
                """
            ),
            {
                "database_name": database_name,
                "table_name": table_name,
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

        if not _table_exists(connection, database_name, "user_favorite_agents"):
            connection.execute(
                text(
                    """
                    CREATE TABLE `user_favorite_agents` (
                      `id` BIGINT NOT NULL AUTO_INCREMENT,
                      `user_id` BIGINT NOT NULL,
                      `agent_code` VARCHAR(64) NOT NULL,
                      `sort_order` INT NOT NULL DEFAULT 0,
                      `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                      `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                        ON UPDATE CURRENT_TIMESTAMP(6),
                      PRIMARY KEY (`id`),
                      UNIQUE KEY `uq_user_favorite_agents_user_agent` (`user_id`, `agent_code`),
                      KEY `ix_user_favorite_agents_user_id` (`user_id`),
                      KEY `ix_user_favorite_agents_agent_code` (`agent_code`),
                      KEY `ix_user_favorite_agents_user_sort` (`user_id`, `sort_order`),
                      CONSTRAINT `fk_user_favorite_agents_user_id`
                        FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
                      CONSTRAINT `fk_user_favorite_agents_agent_code`
                        FOREIGN KEY (`agent_code`) REFERENCES `agents` (`code`) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            )

        _add_column(connection, database_name, "task_runs", "deleted_at", "DATETIME(6) NULL")
        _add_column(connection, database_name, "files", "deleted_at", "DATETIME(6) NULL")
        _create_index(connection, database_name, "task_runs", "ix_task_runs_deleted_at", "(`deleted_at`)")
        _create_index(connection, database_name, "files", "ix_files_deleted_at", "(`deleted_at`)")


if __name__ == "__main__":
    run_migration()
    print("Phase 13.1 UI/UX migration completed.")
