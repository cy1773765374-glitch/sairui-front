from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.file import File
from app.models.task_run import TERMINAL_RUN_STATUSES, TaskRun
from app.models.user import User
from app.services.file_service import files_to_gateway_payload, validate_and_bind_upload_files
from app.services.ppt_generation_service import requires_attachment_content
from app.services.run_event_service import append_run_event
from app.services.run_service import (
    mark_task_run_cancelled,
    mark_task_run_failed,
    mark_task_run_running,
    mark_task_run_success,
    patch_task_run_raw_payload,
    touch_task_run_heartbeat,
    upsert_assistant_message_for_run,
)
from app.services.runners.base import AgentRunner, RunnerInput
from app.services.task_queue import task_queue
from app.services.workspace_service import resolve_agent_workspace
from app.services.ws_connection_manager import connection_manager

logger = logging.getLogger(__name__)

PPT_UNSUPPORTED_ATTACHMENT_MESSAGE = (
    "PPT 生成失败：当前 PPT 生成脚本尚未支持读取上传文件内容，请补充文字需求或先扩展附件解析能力。"
)


def python_executable(workspace: Path) -> str:
    venv_python = workspace / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    windows_venv_python = workspace / ".venv" / "Scripts" / "python.exe"
    if windows_venv_python.exists():
        return str(windows_venv_python)
    return "python3" if os.name != "nt" else "python"


def _venv_bin_dir(workspace: Path) -> Path | None:
    venv_bin = workspace / ".venv" / "bin"
    if venv_bin.exists():
        return venv_bin
    windows_venv_bin = workspace / ".venv" / "Scripts"
    if windows_venv_bin.exists():
        return windows_venv_bin
    return None


def build_ppt_generation_env(workspace: Path, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("PYTHONHOME", None)

    venv_bin = _venv_bin_dir(workspace)
    if venv_bin is not None:
        existing_path = env.get("PATH", "")
        env["PATH"] = str(venv_bin) + (os.pathsep + existing_path if existing_path else "")
        env["VIRTUAL_ENV"] = str(workspace / ".venv")
    return env


def build_ppt_generation_command(
    *,
    workspace: Path,
    prompt: str,
    sender_name: str,
    sender_open_id: str,
) -> list[str]:
    return [
        python_executable(workspace),
        "scripts/generate_catalog_ppt.py",
        "--prompt",
        prompt,
        "--sender-name",
        sender_name,
        "--sender-open-id",
        sender_open_id,
        "--json",
    ]


def extract_json_object(stdout: str) -> dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        raise ValueError("stdout is empty")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    last_object: dict[str, Any] | None = None
    last_ok_object: dict[str, Any] | None = None
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            last_object = data
            if "ok" in data and any(key in data for key in ("reply_text", "windows_path", "pptx_path", "error", "run_dir")):
                last_ok_object = data
            elif "ok" in data and last_ok_object is None:
                last_ok_object = data
    if last_ok_object is not None:
        return last_ok_object
    if last_object is not None:
        return last_object
    raise ValueError("no JSON object found in stdout")


def ppt_success_text(data: dict[str, Any]) -> str:
    return str(data.get("reply_text") or data.get("windows_path") or data.get("pptx_path") or "").strip()


def ppt_failure_text(data: dict[str, Any] | None = None, fallback: str | None = None) -> str:
    error = ""
    if data:
        error = str(data.get("error") or "").strip()
    if not error:
        error = (fallback or "未知错误").strip()
    return f"PPT 生成失败：{error}"


def _truncate(value: str, max_length: int = 4000) -> str:
    text = value or ""
    if len(text) <= max_length:
        return text
    return text[-max_length:]


def _format_duration(seconds: int | None) -> str:
    seconds = max(0, int(seconds or 0))
    minutes, remaining = divmod(seconds, 60)
    if minutes:
        return f"{minutes}分{remaining}秒"
    return f"{remaining}秒"


class PPTGenerationJobRunner(AgentRunner):
    name = "ppt_generation_job"

    async def run(self, runner_input: RunnerInput, cancel_event: asyncio.Event) -> None:
        started_monotonic = time.monotonic()
        process: asyncio.subprocess.Process | None = None
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

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

        async def append_event(
            event_type: str,
            *,
            phase: str | None = None,
            message: str | None = None,
            payload: dict[str, Any] | None = None,
        ) -> None:
            duration_seconds = int(time.monotonic() - started_monotonic)
            with SessionLocal() as db:
                run = db.get(TaskRun, runner_input.run_id)
                if run is not None and run.status not in TERMINAL_RUN_STATUSES:
                    run.duration_seconds = duration_seconds
                    touch_task_run_heartbeat(db, run)
                append_run_event(
                    db,
                    runner_input.run_id,
                    event_type,
                    phase=phase,
                    message=message,
                    payload={**(payload or {}), "duration_seconds": duration_seconds},
                )
            await broadcast_status(status_value="running", message=message, phase=phase)

        async def read_stream(reader: asyncio.StreamReader | None, target: list[str], event_type: str) -> None:
            if reader is None:
                return
            while True:
                line = await reader.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").rstrip()
                target.append(text)
                del target[:-80]
                logger.info("[ppt-runner] run_id=%s %s=%s", runner_input.run_id, event_type, text)
                if event_type == "stderr" and text:
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
                script_path = workspace / "scripts" / "generate_catalog_ppt.py"
                if not script_path.is_file():
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "code": "PPT_SCRIPT_MISSING",
                            "message": f"PPT 生成脚本不存在：{script_path}",
                        },
                    )

                files = validate_and_bind_upload_files(db, user, conversation.id, runner_input.file_ids)
                attachment_payload = files_to_gateway_payload(files)
                if requires_attachment_content(runner_input.content, files):
                    await self._finish_failed(
                        runner_input,
                        duration_seconds=int(time.monotonic() - started_monotonic),
                        phase="unsupported_attachments",
                        error_message=PPT_UNSUPPORTED_ATTACHMENT_MESSAGE,
                        raw_payload={"attachments": attachment_payload, "files": attachment_payload},
                    )
                    return

                command = build_ppt_generation_command(
                    workspace=workspace,
                    prompt=runner_input.content,
                    sender_name=user.display_name or user.username or "",
                    sender_open_id=str(user.id),
                )
                run.run_type = "job"
                run.task_kind = "long_job"
                run.runner_name = self.name
                run.workspace_path = str(workspace)
                run.timeout_seconds = None
                run.phase = "queued"
                run.progress_message = "PPT 生成任务已入队"
                run.raw_payload = {
                    **(run.raw_payload or {}),
                    "workspace_path": str(workspace),
                    "task_kind": "long_job",
                    "runner_name": self.name,
                    "attachments": attachment_payload,
                    "files": attachment_payload,
                    "command": command,
                    "status": "queued",
                }
                db.commit()

                run = mark_task_run_running(db, run)
                run.phase = "running"
                run.progress_message = "PPT 生成任务运行中"
                run.raw_payload = {
                    **(run.raw_payload or {}),
                    "status": "running",
                    "phase": "running",
                }
                db.commit()

            await append_event("started", phase="starting", message="PPT 生成任务开始执行")
            await append_event("workspace_prepared", phase="workspace", message=str(workspace))
            await append_event(
                "command_started",
                phase="running",
                message="开始执行 generate_catalog_ppt.py",
                payload={"cwd": str(workspace), "command": command},
            )
            logger.info("[ppt-runner] run_id=%s cwd=%s command=%s", runner_input.run_id, workspace, command)

            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=build_ppt_generation_env(workspace),
            )
            stdout_task = asyncio.create_task(read_stream(process.stdout, stdout_lines, "stdout"))
            stderr_task = asyncio.create_task(read_stream(process.stderr, stderr_lines, "stderr"))
            while process.returncode is None:
                if cancel_event.is_set():
                    raise asyncio.CancelledError
                await append_event("heartbeat", phase="running", message="PPT 生成任务运行中")
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    continue

            await asyncio.gather(stdout_task, stderr_task)
            stdout_text = "\n".join(stdout_lines)
            stderr_text = "\n".join(stderr_lines)
            return_code = process.returncode or 0
            duration_seconds = int(time.monotonic() - started_monotonic)
            if return_code != 0:
                await self._finish_failed(
                    runner_input,
                    duration_seconds=duration_seconds,
                    phase="failed",
                    error_message=ppt_failure_text(fallback=_truncate(stderr_text) or f"脚本退出码：{return_code}"),
                    raw_payload={
                        "returncode": return_code,
                        "stdout_tail": _truncate(stdout_text),
                        "stderr_tail": _truncate(stderr_text),
                    },
                )
                return

            try:
                data = extract_json_object(stdout_text)
            except ValueError as exc:
                await self._finish_failed(
                    runner_input,
                    duration_seconds=duration_seconds,
                    phase="json_parse",
                    error_message=ppt_failure_text(fallback=str(exc)),
                    raw_payload={
                        "stdout_tail": _truncate(stdout_text),
                        "stderr_tail": _truncate(stderr_text),
                    },
                )
                return

            if not data.get("ok"):
                await self._finish_failed(
                    runner_input,
                    duration_seconds=duration_seconds,
                    phase="script_failed",
                    error_message=ppt_failure_text(data, fallback=_truncate(stderr_text)),
                    raw_payload={"ppt_json": data, "stderr_tail": _truncate(stderr_text)},
                )
                return

            assistant_text = ppt_success_text(data)
            if not assistant_text:
                await self._finish_failed(
                    runner_input,
                    duration_seconds=duration_seconds,
                    phase="missing_output_path",
                    error_message=ppt_failure_text(fallback="脚本成功返回但未提供 PPT 路径"),
                    raw_payload={"ppt_json": data, "stderr_tail": _truncate(stderr_text)},
                )
                return

            await self._finish_success(
                runner_input,
                duration_seconds=duration_seconds,
                assistant_text=assistant_text,
                data=data,
                stderr_tail=_truncate(stderr_text),
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
                    run.progress_message = "PPT 生成任务已取消"
                    run = mark_task_run_cancelled(db, run, "PPT 生成任务已取消")
                    if conversation is not None:
                        upsert_assistant_message_for_run(
                            db,
                            run=run,
                            conversation=conversation,
                            content=f"PPT 生成已取消。\n耗时：{_format_duration(duration_seconds)}",
                            raw_payload_patch={"status": "cancelled", "duration_seconds": duration_seconds},
                        )
                    append_run_event(db, runner_input.run_id, "cancelled", phase="cancelled", message="PPT 生成任务已取消")
            await broadcast_status(status_value="cancelled", message="PPT 生成任务已取消", phase="cancelled", output_files=[])
        except Exception as exc:
            await stop_process()
            duration_seconds = int(time.monotonic() - started_monotonic)
            if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
                message = str(exc.detail.get("message") or exc.detail.get("detail") or exc.detail)
                payload = {"error_detail": exc.detail}
            else:
                message = str(exc) or "PPT 生成任务执行失败"
                payload = {}
            await self._finish_failed(
                runner_input,
                duration_seconds=duration_seconds,
                phase="failed",
                error_message=ppt_failure_text(fallback=message),
                raw_payload=payload,
            )
        finally:
            task_queue.set_abort(runner_input.run_id, None)

    async def _finish_success(
        self,
        runner_input: RunnerInput,
        *,
        duration_seconds: int,
        assistant_text: str,
        data: dict[str, Any],
        stderr_tail: str,
    ) -> None:
        with SessionLocal() as db:
            run = db.get(TaskRun, runner_input.run_id)
            conversation = db.get(Conversation, runner_input.conversation_id)
            if run is None or conversation is None:
                return
            run.duration_seconds = duration_seconds
            run.phase = "completed"
            run.progress_message = "PPT 生成任务已完成"
            run.raw_payload = {
                **(run.raw_payload or {}),
                "status": "success",
                "phase": "completed",
                "duration_seconds": duration_seconds,
                "task_kind": "long_job",
                "runner_name": self.name,
                "ppt_json": data,
                "windows_path": data.get("windows_path") or data.get("reply_text"),
                "pptx_path": data.get("pptx_path"),
                "run_dir": data.get("run_dir"),
                "render_backend": data.get("render_backend"),
                "stderr_tail": stderr_tail,
            }
            assistant_message = upsert_assistant_message_for_run(
                db,
                run=run,
                conversation=conversation,
                content=assistant_text,
                raw_payload_patch=run.raw_payload,
            )
            assistant_message_id = assistant_message.id
            run = db.get(TaskRun, runner_input.run_id) or run
            run = mark_task_run_success(db, run, output_text=assistant_text, output_dir=str(data.get("run_dir") or run.output_dir or ""))
            run.output_files_json = []
            db.commit()
            append_run_event(db, runner_input.run_id, "completed", phase="completed", message="PPT 生成任务已完成")

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
                "status": "success",
                "phase": "completed",
                "message": "PPT 生成任务已完成",
                "progress_message": "PPT 生成任务已完成",
                "runner_name": self.name,
                "task_kind": "long_job",
                "duration_seconds": duration_seconds,
                "output_files": [],
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
                run = mark_task_run_failed(db, run, error_message, output_text=error_message)
            else:
                patch_task_run_raw_payload(db, run, run.raw_payload, allow_terminal_update=True)
            if conversation is not None:
                assistant_message = upsert_assistant_message_for_run(
                    db,
                    run=run,
                    conversation=conversation,
                    content=error_message,
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
                "runner_name": self.name,
                "task_kind": "long_job",
                "duration_seconds": duration_seconds,
                "output_files": [],
            },
        )
