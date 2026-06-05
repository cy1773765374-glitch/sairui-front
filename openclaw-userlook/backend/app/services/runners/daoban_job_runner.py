from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.file import File
from app.models.task_run import TERMINAL_RUN_STATUSES, TaskRun, TaskRunStatus
from app.models.user import User
from app.services.daoban_service import DAOBAN_EXPECTED_OUTPUTS, is_pdf_file, sync_daoban_files_to_workspace
from app.services.file_service import register_output_files, validate_and_bind_upload_files
from app.services.run_event_service import append_run_event
from app.services.run_service import (
    mark_task_run_cancelled,
    mark_task_run_failed,
    mark_task_run_running,
    mark_task_run_success,
    patch_task_run_raw_payload,
    upsert_assistant_message_for_run,
)
from app.services.runners.base import AgentRunner, RunnerInput
from app.services.task_queue import task_queue
from app.services.workspace_service import resolve_agent_workspace
from app.services.ws_connection_manager import connection_manager

logger = logging.getLogger(__name__)


def _safe_label(value: str, max_length: int = 40) -> str:
    label = re.sub(r"[\x00-\x1f<>:\"/\\|?*\s]+", "-", (value or "").strip()).strip("-")
    return (label or "daoban")[:max_length]


def _format_duration(seconds: int | None) -> str:
    seconds = max(0, int(seconds or 0))
    minutes, remaining = divmod(seconds, 60)
    if minutes:
        return f"{minutes}分{remaining}秒"
    return f"{remaining}秒"


def _python_executable(workspace: Path) -> str:
    venv_python = workspace / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    windows_venv_python = workspace / ".venv" / "Scripts" / "python.exe"
    if windows_venv_python.exists():
        return str(windows_venv_python)
    return "python"


def build_daoban_command(
    *,
    workspace: Path,
    pdf_path: str,
    prompt: str,
    output_dir: str,
) -> list[str]:
    return [
        _python_executable(workspace),
        "scripts/run_daoban_job.py",
        "--pdf",
        pdf_path,
        "--prompt",
        prompt,
        "--job-label",
        prompt,
        "--clip-mode",
        "shape",
        "--dieline-source",
        "auto",
        "--export-mode",
        "both",
        "--layout-mode",
        "shape-aware",
        "--preflight-mode",
        "warn",
        "--ai-handoff",
        "--run-dir",
        output_dir,
    ]


def build_daoban_output_dir(run_id: int, prompt: str) -> str:
    date_part = datetime.now().strftime("%Y-%m-%d")
    return str(Path(get_settings().openclaw_daoban_output_root).expanduser() / f"{date_part}-run-{run_id}-{_safe_label(prompt)}")


def inspect_daoban_outputs(output_dir: str) -> tuple[list[str], list[str], bool]:
    root = Path(output_dir).expanduser()
    expected = DAOBAN_EXPECTED_OUTPUTS
    missing = [name for name in expected if not (root / name).is_file()]
    found = [name for name in expected if (root / name).is_file()]
    has_pdf = any((root / name).is_file() for name in ("out.pdf", "out_print.pdf", "out_preview.pdf"))
    has_png = (root / "out.png").is_file()
    has_report = any((root / name).is_file() for name in ("report.json", "qc_report.json"))
    return found, missing, bool(has_pdf and has_png and has_report)


class DaobanJobRunner(AgentRunner):
    name = "daoban_job"

    async def run(self, runner_input: RunnerInput, cancel_event: asyncio.Event) -> None:
        started_monotonic = time.monotonic()
        process: asyncio.subprocess.Process | None = None
        stderr_tail: list[str] = []

        async def broadcast_status(
            *,
            status_value: str,
            message: str | None = None,
            phase: str | None = None,
            output_files: list | None = None,
        ) -> None:
            duration_seconds = int(time.monotonic() - started_monotonic)
            payload: dict[str, Any] = {
                "type": "run_status",
                "conversation_id": runner_input.conversation_id,
                "run_id": runner_input.run_id,
                "status": status_value,
                "runner_name": self.name,
                "task_kind": "long_job",
                "duration_seconds": duration_seconds,
            }
            if phase is not None:
                payload["phase"] = phase
            if message is not None:
                payload["message"] = message
                payload["progress_message"] = message
            if output_files is not None:
                payload["output_files"] = output_files
            await connection_manager.broadcast_json(runner_input.conversation_id, payload)

        def request_stop() -> None:
            cancel_event.set()
            if process is not None and process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()

        async def stop_process() -> None:
            if process is None or process.returncode is not None:
                return
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()

        async def append_event(event_type: str, *, phase: str | None = None, message: str | None = None, payload: dict[str, Any] | None = None) -> None:
            duration_seconds = int(time.monotonic() - started_monotonic)
            with SessionLocal() as db:
                run = db.get(TaskRun, runner_input.run_id)
                if run is not None and run.status not in TERMINAL_RUN_STATUSES:
                    run.duration_seconds = duration_seconds
                append_run_event(
                    db,
                    runner_input.run_id,
                    event_type,
                    phase=phase,
                    message=message,
                    payload={**(payload or {}), "duration_seconds": duration_seconds},
                )
            await broadcast_status(status_value="running", message=message, phase=phase)

        async def read_stream(reader: asyncio.StreamReader | None, event_type: str) -> None:
            if reader is None:
                return
            while True:
                line = await reader.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").rstrip()
                if event_type == "stderr" and text:
                    stderr_tail.append(text)
                    del stderr_tail[:-20]
                logger.info("[daoban-runner] run_id=%s %s=%s", runner_input.run_id, event_type, text)
                await append_event(event_type, phase="running", message=text)

        task_queue.set_abort(runner_input.run_id, request_stop)
        try:
            with SessionLocal() as db:
                run = db.get(TaskRun, runner_input.run_id)
                user = db.get(User, runner_input.user_id)
                agent = db.get(Agent, runner_input.agent_id)
                conversation = db.get(Conversation, runner_input.conversation_id)
                if run is None or user is None or agent is None or conversation is None:
                    return
                if run.status in TERMINAL_RUN_STATUSES:
                    return

                workspace = resolve_agent_workspace(agent, require_exists=True)
                script_path = workspace / "scripts" / "run_daoban_job.py"
                if not script_path.is_file():
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "code": "DAOBAN_SCRIPT_MISSING",
                            "message": f"刀版执行脚本不存在：{script_path}",
                        },
                    )

                run.run_type = "job"
                run.task_kind = "long_job"
                run.runner_name = self.name
                run.workspace_path = str(workspace)
                run.timeout_seconds = None
                run.phase = "queued"
                run.progress_message = "刀版任务已入队"
                run.raw_payload = {
                    **(run.raw_payload or {}),
                    "workspace_path": str(workspace),
                    "task_kind": "long_job",
                    "runner_name": self.name,
                    "status": "queued",
                }
                db.commit()

                run = mark_task_run_running(db, run)
                files = validate_and_bind_upload_files(db, user, conversation.id, runner_input.file_ids)
                gateway_files, daoban_payload = sync_daoban_files_to_workspace(
                    db,
                    run=run,
                    agent=agent,
                    content=runner_input.content,
                    files=files,
                )
                pdf_file = next((file for file in files if is_pdf_file(file)), None)
                if pdf_file is None or not pdf_file.workspace_path:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "code": "DAOBAN_PDF_REQUIRED",
                            "message": "刀版合成 Agent 需要 PDF 刀版文件。",
                        },
                    )
                output_dir = build_daoban_output_dir(run.id, runner_input.content)
                Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
                command = build_daoban_command(
                    workspace=workspace,
                    pdf_path=pdf_file.workspace_path,
                    prompt=runner_input.content,
                    output_dir=output_dir,
                )
                run.output_dir = output_dir
                run.raw_payload = {
                    **(run.raw_payload or {}),
                    **daoban_payload,
                    "files": gateway_files,
                    "workspace_path": str(workspace),
                    "output_dir": output_dir,
                    "command": command,
                    "status": "running",
                }
                db.commit()

            await append_event("started", phase="starting", message="刀版任务开始执行")
            await append_event("workspace_prepared", phase="workspace", message=str(workspace))
            await append_event("command_started", phase="running", message="开始执行 run_daoban_job.py", payload={"cwd": str(workspace), "command": command})
            logger.info("[daoban-runner] run_id=%s cwd=%s command=%s", runner_input.run_id, workspace, command)

            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_task = asyncio.create_task(read_stream(process.stdout, "stdout"))
            stderr_task = asyncio.create_task(read_stream(process.stderr, "stderr"))
            while process.returncode is None:
                if cancel_event.is_set():
                    raise asyncio.CancelledError
                await append_event("heartbeat", phase="running", message="刀版任务运行中")
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    continue

            await asyncio.gather(stdout_task, stderr_task)
            return_code = process.returncode or 0
            duration_seconds = int(time.monotonic() - started_monotonic)
            if return_code != 0:
                await self._finish_failed(
                    runner_input,
                    duration_seconds=duration_seconds,
                    phase="failed",
                    error_message="\n".join(stderr_tail[-10:]) or f"刀版脚本退出码：{return_code}",
                    raw_payload={"returncode": return_code, "stderr_tail": stderr_tail[-20:]},
                )
                return

            found_outputs, missing_outputs, minimum_ok = inspect_daoban_outputs(output_dir)
            if not minimum_ok:
                await self._finish_failed(
                    runner_input,
                    duration_seconds=duration_seconds,
                    phase="output_check",
                    error_message="刀版输出不完整，最低完成文件未全部生成。",
                    raw_payload={"found_outputs": found_outputs, "missing_outputs": missing_outputs},
                )
                return

            await self._finish_success(
                runner_input,
                duration_seconds=duration_seconds,
                output_dir=output_dir,
                found_outputs=found_outputs,
                missing_outputs=missing_outputs,
            )
        except asyncio.CancelledError:
            await stop_process()
            duration_seconds = int(time.monotonic() - started_monotonic)
            with SessionLocal() as db:
                run = db.get(TaskRun, runner_input.run_id)
                conversation = db.get(Conversation, runner_input.conversation_id)
                if run is not None and run.status not in TERMINAL_RUN_STATUSES:
                    run.duration_seconds = duration_seconds
                    run.phase = "cancelled"
                    run.progress_message = "刀版任务已取消"
                    run = mark_task_run_cancelled(db, run, "刀版任务已取消")
                    if conversation is not None:
                        upsert_assistant_message_for_run(
                            db,
                            run=run,
                            conversation=conversation,
                            content=f"刀版合成已取消。\n耗时：{_format_duration(duration_seconds)}",
                            raw_payload_patch={"status": "cancelled", "duration_seconds": duration_seconds},
                        )
                    append_run_event(db, runner_input.run_id, "cancelled", phase="cancelled", message="刀版任务已取消")
            await broadcast_status(status_value="cancelled", message="刀版任务已取消", phase="cancelled", output_files=[])
        except Exception as exc:
            await stop_process()
            duration_seconds = int(time.monotonic() - started_monotonic)
            with SessionLocal() as db:
                run = db.get(TaskRun, runner_input.run_id)
                if run is not None and run.status == TaskRunStatus.success:
                    logger.exception("[daoban-runner] run_id=%s post_success_error_ignored", runner_input.run_id)
                    return
            if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
                message = str(exc.detail.get("message") or exc.detail.get("detail") or exc.detail)
                payload = {"error_detail": exc.detail}
            else:
                message = str(exc) or "刀版任务执行失败"
                payload = {}
            await self._finish_failed(
                runner_input,
                duration_seconds=duration_seconds,
                phase="failed",
                error_message=message,
                raw_payload=payload,
            )
        finally:
            task_queue.set_abort(runner_input.run_id, None)

    async def _finish_success(
        self,
        runner_input: RunnerInput,
        *,
        duration_seconds: int,
        output_dir: str,
        found_outputs: list[str],
        missing_outputs: list[str],
    ) -> None:
        missing_text = ""
        if missing_outputs:
            missing_text = "\n\n部分预期文件未找到：\n" + "\n".join(f"- {name}" for name in missing_outputs)
        summary = (
            "已完成刀版合成。\n"
            f"耗时：{_format_duration(duration_seconds)}\n"
            f"输出目录：{output_dir}\n"
            f"PDF：{output_dir}/out.pdf\n"
            f"预览图：{output_dir}/out.png\n"
            f"QC 报告：{output_dir}/qc_report.json\n"
            f"AI 交付文件：{output_dir}/ai_handoff/out_ai.pdf\n"
            "裁切模式：shape\n"
            "布局模式：shape-aware\n"
            "AI 可见图片对象：请以 qc_report / verify 结果为准"
            f"{missing_text}"
        )
        with SessionLocal() as db:
            run = db.get(TaskRun, runner_input.run_id)
            conversation = db.get(Conversation, runner_input.conversation_id)
            user = db.get(User, runner_input.user_id)
            if run is None or conversation is None or user is None:
                return
            run.duration_seconds = duration_seconds
            run.phase = "completed"
            run.progress_message = "刀版任务已完成"
            run.raw_payload = {
                **(run.raw_payload or {}),
                "status": "success",
                "found_outputs": found_outputs,
                "missing_outputs": missing_outputs,
                "duration_seconds": duration_seconds,
                "task_kind": "long_job",
                "runner_name": self.name,
            }
            assistant_message = upsert_assistant_message_for_run(
                db,
                run=run,
                conversation=conversation,
                content=summary,
                raw_payload_patch=run.raw_payload,
            )
            assistant_message_id = assistant_message.id
            run = db.get(TaskRun, runner_input.run_id) or run
            run = mark_task_run_success(db, run, output_text=summary, output_dir=output_dir)
            output_files = register_output_files(db, user.id, output_dir)
            output_files_payload = jsonable_encoder(output_files)
            run.output_files_json = output_files_payload
            db.commit()
            append_run_event(db, runner_input.run_id, "output_detected", phase="completed", message="刀版输出文件已识别", payload={"found_outputs": found_outputs, "missing_outputs": missing_outputs})
            append_run_event(db, runner_input.run_id, "completed", phase="completed", message="刀版任务已完成")
        await connection_manager.broadcast_json(
            runner_input.conversation_id,
            {
                "type": "assistant_done",
                "conversation_id": runner_input.conversation_id,
                "message_id": assistant_message_id,
                "run_id": runner_input.run_id,
                "output_files": output_files_payload,
            },
        )
        await connection_manager.broadcast_json(
            runner_input.conversation_id,
            {
                "type": "run_status",
                "conversation_id": runner_input.conversation_id,
                "run_id": runner_input.run_id,
                "status": "success",
                "phase": "completed",
                "message": "刀版任务已完成",
                "progress_message": "刀版任务已完成",
                "duration_seconds": duration_seconds,
                "output_files": output_files_payload,
            },
        )

    async def _finish_failed(
        self,
        runner_input: RunnerInput,
        *,
        duration_seconds: int,
        phase: str,
        error_message: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        summary = (
            "刀版合成失败。\n"
            f"失败阶段：{phase}\n"
            f"耗时：{_format_duration(duration_seconds)}\n"
            "错误摘要：\n"
            f"{error_message}\n"
            "请检查 PDF 是否为有效刀版文件，或查看任务日志。"
        )
        with SessionLocal() as db:
            run = db.get(TaskRun, runner_input.run_id)
            conversation = db.get(Conversation, runner_input.conversation_id)
            if run is None:
                return
            run.duration_seconds = duration_seconds
            run.phase = phase
            run.progress_message = error_message
            run.raw_payload = {
                **(run.raw_payload or {}),
                **(raw_payload or {}),
                "status": "failed",
                "phase": phase,
                "duration_seconds": duration_seconds,
                "task_kind": "long_job",
                "runner_name": self.name,
            }
            if run.status not in TERMINAL_RUN_STATUSES:
                run = mark_task_run_failed(db, run, error_message, output_text=summary)
            else:
                patch_task_run_raw_payload(db, run, run.raw_payload, allow_terminal_update=True)
            if conversation is not None:
                assistant_message = upsert_assistant_message_for_run(
                    db,
                    run=run,
                    conversation=conversation,
                    content=summary,
                    raw_payload_patch=run.raw_payload,
                )
                assistant_message_id = assistant_message.id
            else:
                assistant_message_id = None
            append_run_event(db, runner_input.run_id, "failed", phase=phase, message=error_message, payload=raw_payload)
        if assistant_message_id is not None:
            await connection_manager.broadcast_json(
                runner_input.conversation_id,
                {
                    "type": "assistant_done",
                    "conversation_id": runner_input.conversation_id,
                    "message_id": assistant_message_id,
                    "run_id": runner_input.run_id,
                    "output_files": [],
                },
            )
        await connection_manager.broadcast_json(
            runner_input.conversation_id,
            {
                "type": "run_status",
                "conversation_id": runner_input.conversation_id,
                "run_id": runner_input.run_id,
                "status": "failed",
                "phase": phase,
                "message": error_message,
                "progress_message": error_message,
                "duration_seconds": duration_seconds,
                "output_files": [],
            },
        )
