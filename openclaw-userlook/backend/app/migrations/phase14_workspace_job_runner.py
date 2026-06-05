from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.database import engine


WORKSPACE_BY_CODE = {
    "main": ("/home/cy/.openclaw/workspace", "chat"),
    "recruitment": ("/home/cy/.openclaw/workspace-recruitment", "auto"),
    "ragagent": ("/home/cy/.openclaw/workspace-ragagent", "auto"),
    "spider": ("/home/cy/.openclaw/workspace-spider", "auto"),
    "spider_1688": ("/home/cy/.openclaw/workspace-spider", "auto"),
    "reminder": ("/home/cy/.openclaw/workspace", "chat"),
    "xingzheng": ("/home/cy/.openclaw/workspace-xingzheng_a", "auto"),
    "xingzheng_a": ("/home/cy/.openclaw/workspace-xingzheng_a", "auto"),
    "image_daoban": ("/home/cy/.openclaw/workspace-image-daoban", "job"),
    "image-daoban": ("/home/cy/.openclaw/workspace-image-daoban", "job"),
    "mysql_analysis": ("/home/cy/.openclaw/workspace-huizong-ceshi", "auto"),
    "huizong_ceshi": ("/home/cy/.openclaw/workspace-huizong-ceshi", "auto"),
    "huizong-ceshi": ("/home/cy/.openclaw/workspace-huizong-ceshi", "auto"),
    "ppt_generation": ("/home/cy/.openclaw/workspace", "auto"),
}


def _dialect(connection) -> str:
    return connection.dialect.name


def _columns(connection, table_name: str) -> set[str]:
    inspector = inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(connection, table_name: str) -> set[str]:
    inspector = inspect(connection)
    if not inspector.has_table(table_name):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _table_exists(connection, table_name: str) -> bool:
    return inspect(connection).has_table(table_name)


def _add_column(connection, table_name: str, column_name: str, mysql_definition: str, sqlite_definition: str | None = None) -> None:
    if column_name in _columns(connection, table_name):
        return
    definition = mysql_definition if _dialect(connection) != "sqlite" else (sqlite_definition or mysql_definition)
    connection.execute(text(f"ALTER TABLE `{table_name}` ADD COLUMN `{column_name}` {definition}"))


def _create_index(connection, table_name: str, index_name: str, columns: str) -> None:
    if index_name in _indexes(connection, table_name):
        return
    connection.execute(text(f"CREATE INDEX `{index_name}` ON `{table_name}` {columns}"))


def _create_pending_task_inputs(connection) -> None:
    if _table_exists(connection, "pending_task_inputs"):
        return
    if _dialect(connection) == "sqlite":
        connection.execute(
            text(
                """
                CREATE TABLE `pending_task_inputs` (
                    `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                    `user_id` BIGINT NOT NULL,
                    `conversation_id` BIGINT NOT NULL,
                    `agent_id` BIGINT NOT NULL,
                    `agent_code` VARCHAR(64) NOT NULL,
                    `task_type` VARCHAR(64) NOT NULL,
                    `pending_text` TEXT NULL,
                    `pending_file_ids` JSON NULL,
                    `source_message_ids` JSON NULL,
                    `status` VARCHAR(32) NOT NULL DEFAULT 'pending',
                    `expires_at` DATETIME NULL,
                    `consumed_by_run_id` BIGINT NULL,
                    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        return
    connection.execute(
        text(
            """
            CREATE TABLE `pending_task_inputs` (
                `id` BIGINT NOT NULL AUTO_INCREMENT,
                `user_id` BIGINT NOT NULL,
                `conversation_id` BIGINT NOT NULL,
                `agent_id` BIGINT NOT NULL,
                `agent_code` VARCHAR(64) NOT NULL,
                `task_type` VARCHAR(64) NOT NULL,
                `pending_text` TEXT NULL,
                `pending_file_ids` JSON NULL,
                `source_message_ids` JSON NULL,
                `status` VARCHAR(32) NOT NULL DEFAULT 'pending',
                `expires_at` DATETIME(6) NULL,
                `consumed_by_run_id` BIGINT NULL,
                `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
                PRIMARY KEY (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def _create_run_events(connection) -> None:
    if _table_exists(connection, "run_events"):
        return
    if _dialect(connection) == "sqlite":
        connection.execute(
            text(
                """
                CREATE TABLE `run_events` (
                    `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                    `run_id` BIGINT NOT NULL,
                    `event_type` VARCHAR(64) NOT NULL,
                    `phase` VARCHAR(100) NULL,
                    `message` TEXT NULL,
                    `payload_json` JSON NULL,
                    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        return
    connection.execute(
        text(
            """
            CREATE TABLE `run_events` (
                `id` BIGINT NOT NULL AUTO_INCREMENT,
                `run_id` BIGINT NOT NULL,
                `event_type` VARCHAR(64) NOT NULL,
                `phase` VARCHAR(100) NULL,
                `message` TEXT NULL,
                `payload_json` JSON NULL,
                `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                PRIMARY KEY (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def _seed_agent_workspaces(connection) -> None:
    for code, (workspace_path, execution_mode) in WORKSPACE_BY_CODE.items():
        connection.execute(
            text(
                """
                UPDATE `agents`
                SET
                    `workspace_path` = COALESCE(NULLIF(`workspace_path`, ''), :workspace_path),
                    `execution_mode` = COALESCE(NULLIF(`execution_mode`, ''), :execution_mode)
                WHERE `code` = :code OR `openclaw_agent_id` = :code
                """
            ),
            {
                "code": code,
                "workspace_path": workspace_path,
                "execution_mode": execution_mode,
            },
        )


def run_migration() -> None:
    with engine.begin() as connection:
        _add_column(connection, "agents", "workspace_path", "VARCHAR(500) NULL")
        _add_column(connection, "agents", "execution_mode", "VARCHAR(50) NULL")

        _add_column(connection, "task_runs", "task_kind", "VARCHAR(50) NULL")
        _add_column(connection, "task_runs", "runner_name", "VARCHAR(100) NULL")
        _add_column(connection, "task_runs", "workspace_path", "VARCHAR(500) NULL")
        _add_column(connection, "task_runs", "phase", "VARCHAR(100) NULL")
        _add_column(connection, "task_runs", "progress_message", "TEXT NULL")
        _add_column(connection, "task_runs", "duration_seconds", "INT NULL")

        _create_pending_task_inputs(connection)
        _create_run_events(connection)

        _create_index(connection, "pending_task_inputs", "ix_pending_task_user_scope", "(`user_id`, `conversation_id`, `agent_id`, `task_type`, `status`)")
        _create_index(connection, "pending_task_inputs", "ix_pending_task_expires_at", "(`expires_at`)")
        _create_index(connection, "run_events", "ix_run_events_run_id_created_at", "(`run_id`, `created_at`)")
        _create_index(connection, "run_events", "ix_run_events_event_type", "(`event_type`)")

        _seed_agent_workspaces(connection)


if __name__ == "__main__":
    run_migration()
    print("Phase 14 workspace job runner migration completed.")
