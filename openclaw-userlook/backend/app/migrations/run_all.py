from __future__ import annotations

from collections.abc import Callable

from app.migrations.phase11_task_run_lifecycle import run_migration as run_phase11_migration
from app.migrations.phase12_streaming_persistence import run_migration as run_phase12_migration
from app.migrations.phase12_3_session_isolation import run_migration as run_phase12_3_migration
from app.migrations.phase13_1_uiux import run_migration as run_phase13_1_migration
from app.migrations.phase13_2_uiux import run_migration as run_phase13_2_migration
from app.migrations.phase13_3_upload_files import run_migration as run_phase13_3_migration
from app.migrations.phase13_4_daoban_file_chain import run_migration as run_phase13_4_migration
from app.migrations.phase14_workspace_job_runner import run_migration as run_phase14_migration


MIGRATIONS: list[tuple[str, Callable[[], None]]] = [
    ("phase11_task_run_lifecycle", run_phase11_migration),
    ("phase12_streaming_persistence", run_phase12_migration),
    ("phase12_3_session_isolation", run_phase12_3_migration),
    ("phase13_1_uiux", run_phase13_1_migration),
    ("phase13_2_uiux", run_phase13_2_migration),
    ("phase13_3_upload_files", run_phase13_3_migration),
    ("phase13_4_daoban_file_chain", run_phase13_4_migration),
    ("phase14_workspace_job_runner", run_phase14_migration),
]


def run_all_migrations() -> None:
    for name, run_migration in MIGRATIONS:
        run_migration()
        print(f"{name} completed.")


if __name__ == "__main__":
    run_all_migrations()
