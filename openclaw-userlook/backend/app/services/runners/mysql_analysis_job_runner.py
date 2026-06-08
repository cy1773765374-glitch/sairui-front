from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.task_run import TERMINAL_RUN_STATUSES, TaskRun
from app.models.user import User
from app.services.file_service import register_output_files
from app.services.mysql_analysis_service import (
    MYSQL_ANALYSIS_RUNNER_NAME,
    MYSQL_ANALYSIS_SCRIPT_REL,
    ParsedMysqlAnalysisRequest,
    build_mysql_analysis_command,
    build_mysql_analysis_env,
    build_mysql_failure_text,
    build_mysql_success_text,
    extract_json_object,
    find_mysql_output_dir,
    load_mysql_report_summary,
    load_mysql_run_meta,
    parse_mysql_analysis_request,
    resolve_mysql_analysis_output_root,
    sanitize_mysql_analysis_command,
    sanitize_mysql_analysis_payload,
    sanitize_mysql_analysis_text,
)
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


def _format_duration(seconds: int | None) -> str:
    seconds = max(0, int(seconds or 0))
    minutes, remaining = divmod(seconds, 60)
    if minutes:
        return f"{minutes}分{remaining}秒"
    return f"{remaining}秒"


def _request_payload_from_run(run: TaskRun, content: str) -> ParsedMysqlAnalysisRequest | None:
    raw_payload = run.raw_payload if isinstance(run.raw_payload, dict) else {}
    mysql_payload = raw_payload.get("mysql_analysis")
    if isinstance(mysql_payload, dict):
        start_date = str(mysql_payload.get("start_date") or "").strip()
        end_date = str(mysql_payload.get("end_date") or "").strip()
        if start_date and end_date:
            union_id = str(mysql_payload.get("union_id") or "").strip() or None
            default_year_value = mysql_payload.get("default_year")
            default_year = int(default_year_value) if isinstance(default_year_value, int | str) and str(default_year_value).isdigit() else None
            return ParsedMysqlAnalysisRequest(
                start_date=start_date,
                end_date=end_date,
                union_id=union_id,
                default_year=default_year,
                date_source=str(mysql_payload.get("date_source") or ""),
            )
    return parse_mysql_analysis_request(content)


class MySQLAnalysisJobRunner(AgentRunner):
    name = MYSQL_ANALYSIS_RUNNER_NAME

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

        def terminate_process_group(term_signal: int = signal.SIGTERM) -> None:
            if process is None or process.returncode is not None:
                return
            with contextlib.suppress(ProcessLookupError, PermissionError):
                if os.name != "nt":
                    os.killpg(process.pid, term_signal)
                else:
                    process.terminate()

        def request_stop() -> None:
            cancel_event.set()
            terminate_process_group(signal.SIGTERM)

        async def stop_process() -> None:
            if process is None or process.returncode is not None:
                return
            terminate_process_group(signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError, PermissionError):
                        if os.name != "nt":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
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
            safe_message = sanitize_mysql_analysis_text(message)
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
                    message=safe_message,
                    payload={**(payload or {}), "duration_seconds": duration_seconds},
                )
            await broadcast_status(status_value="running", message=safe_message, phase=phase)

        async def read_stream(reader: asyncio.StreamReader | None, target: list[str], event_type: str) -> None:
            if reader is None:
                return
            while True:
                line = await reader.readline()
                if not line:
                    return
                text = sanitize_mysql_analysis_text(line.decode("utf-8", errors="replace").rstrip())
                target.append(text)
                del target[:-80]
                logger.info("[mysql-analysis-runner] run_id=%s %s=%s", runner_input.run_id, event_type, text)
                if text:
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

                parsed_request = _request_payload_from_run(run, runner_input.content)
                if parsed_request is None:
                    await self._finish_failed(
                        runner_input,
                        duration_seconds=int(time.monotonic() - started_monotonic),
                        phase="参数解析",
                        error_message="缺少可解析的开始日期和结束日期。",
                    )
                    return

                workspace = resolve_agent_workspace(agent, require_exists=True)
                script_path = workspace / MYSQL_ANALYSIS_SCRIPT_REL
                if not script_path.is_file():
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "code": "MYSQL_ANALYSIS_SCRIPT_MISSING",
                            "message": f"MySQL 分析脚本不存在：{script_path}",
                        },
                    )

                output_root = resolve_mysql_analysis_output_root(workspace)
                asker = (user.display_name or user.username or str(user.id) or "未知用户").strip() or "未知用户"
                command = build_mysql_analysis_command(
                    workspace=workspace,
                    start_date=parsed_request.start_date,
                    end_date=parsed_request.end_date,
                    union_id=parsed_request.union_id,
                    asker=asker,
                    question=runner_input.content,
                )
                safe_command = sanitize_mysql_analysis_command(command)
                run.run_type = "job"
                run.task_kind = "long_job"
                run.runner_name = self.name
                run.workspace_path = str(workspace)
                run.timeout_seconds = None
                run.phase = "queued"
                run.progress_message = "MySQL 分析任务已入队"
                run.raw_payload = {
                    **(run.raw_payload or {}),
                    "workspace_path": str(workspace),
                    "output_root": output_root,
                    "task_kind": "long_job",
                    "runner_name": self.name,
                    "mysql_analysis": parsed_request.to_payload(),
                    "command": safe_command,
                    "status": "queued",
                }
                db.commit()

                run = mark_task_run_running(db, run)
                run.phase = "running"
                run.progress_message = "MySQL 分析任务运行中"
                run.raw_payload = {
                    **(run.raw_payload or {}),
                    "status": "running",
                    "phase": "running",
                }
                db.commit()

            await append_event("started", phase="starting", message="MySQL 分析任务开始执行")
            await append_event("workspace_prepared", phase="workspace", message=str(workspace))
            await append_event(
                "command_started",
                phase="running",
                message="开始执行 run_supplier_shipment_report.py",
                payload={"cwd": str(workspace), "command": safe_command, "output_root": output_root},
            )
            logger.info("[mysql-analysis-runner] run_id=%s cwd=%s command=%s", runner_input.run_id, workspace, safe_command)

            process_kwargs: dict[str, Any] = {}
            if os.name != "nt":
                process_kwargs["start_new_session"] = True
            else:
                process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=build_mysql_analysis_env(workspace, output_root=output_root),
                **process_kwargs,
            )
            stdout_task = asyncio.create_task(read_stream(process.stdout, stdout_lines, "stdout"))
            stderr_task = asyncio.create_task(read_stream(process.stderr, stderr_lines, "stderr"))
            while process.returncode is None:
                if cancel_event.is_set():
                    raise asyncio.CancelledError
                await append_event("heartbeat", phase="running", message="MySQL 分析任务运行中")
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
                    phase="MySQL 查询",
                    error_message="\n".join(stderr_lines[-10:]) or f"脚本退出码：{return_code}",
                    raw_payload={
                        "returncode": return_code,
                        "stdout_tail": sanitize_mysql_analysis_text(stdout_text),
                        "stderr_tail": sanitize_mysql_analysis_text(stderr_text),
                    },
                )
                return

            stdout_json = extract_json_object(stdout_text)
            if stdout_json and stdout_json.get("ok") is False:
                await self._finish_failed(
                    runner_input,
                    duration_seconds=duration_seconds,
                    phase="MySQL 查询",
                    error_message=str(stdout_json.get("error") or stdout_json.get("message") or "脚本返回失败"),
                    raw_payload={"stdout_json": stdout_json, "stderr_tail": sanitize_mysql_analysis_text(stderr_text)},
                )
                return

            output_dir = find_mysql_output_dir(stdout_json=stdout_json, output_root=output_root)
            if output_dir is None:
                await self._finish_failed(
                    runner_input,
                    duration_seconds=duration_seconds,
                    phase="文件输出",
                    error_message="脚本成功退出，但未找到 report_summary.md、run_meta.json 或输出目录。",
                    raw_payload={
                        "stdout_json": stdout_json,
                        "stdout_tail": sanitize_mysql_analysis_text(stdout_text),
                        "stderr_tail": sanitize_mysql_analysis_text(stderr_text),
                    },
                )
                return

            report_summary = load_mysql_report_summary(output_dir)
            run_meta = load_mysql_run_meta(output_dir)
            assistant_text = build_mysql_success_text(
                parsed_request=parsed_request,
                output_dir=output_dir,
                report_summary=report_summary,
                run_meta=run_meta,
            )
            await self._finish_success(
                runner_input,
                duration_seconds=duration_seconds,
                assistant_text=assistant_text,
                output_dir=output_dir,
                parsed_request=parsed_request,
                run_meta=run_meta,
                stdout_json=stdout_json,
                stderr_tail=sanitize_mysql_analysis_text(stderr_text),
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
                    run.progress_message = "MySQL 分析任务已取消"
                    run = mark_task_run_cancelled(db, run, "MySQL 分析任务已取消")
                    if conversation is not None:
                        upsert_assistant_message_for_run(
                            db,
                            run=run,
                            conversation=conversation,
                            content=f"MySQL 分析任务已取消。\n耗时：{_format_duration(duration_seconds)}",
                            raw_payload_patch={"status": "cancelled", "duration_seconds": duration_seconds},
                        )
                    append_run_event(db, runner_input.run_id, "cancelled", phase="cancelled", message="MySQL 分析任务已取消")
            await broadcast_status(status_value="cancelled", message="MySQL 分析任务已取消", phase="cancelled", output_files=[])
        except Exception as exc:
            await stop_process()
            duration_seconds = int(time.monotonic() - started_monotonic)
            if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
                message = str(exc.detail.get("message") or exc.detail.get("detail") or exc.detail)
                payload = {"error_detail": exc.detail}
                phase = "脚本启动"
            else:
                message = str(exc) or "MySQL 分析任务执行失败"
                payload = {}
                phase = "未知"
            await self._finish_failed(
                runner_input,
                duration_seconds=duration_seconds,
                phase=phase,
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
        assistant_text: str,
        output_dir: Path,
        parsed_request: ParsedMysqlAnalysisRequest,
        run_meta: dict[str, Any] | None,
        stdout_json: dict[str, Any] | None,
        stderr_tail: str,
    ) -> None:
        with SessionLocal() as db:
            run = db.get(TaskRun, runner_input.run_id)
            conversation = db.get(Conversation, runner_input.conversation_id)
            user = db.get(User, runner_input.user_id)
            if run is None or conversation is None or user is None:
                return
            run.duration_seconds = duration_seconds
            run.phase = "completed"
            run.progress_message = "MySQL 分析任务已完成"
            run.raw_payload = {
                **(run.raw_payload or {}),
                "status": "success",
                "phase": "completed",
                "duration_seconds": duration_seconds,
                "task_kind": "long_job",
                "runner_name": self.name,
                "mysql_analysis": parsed_request.to_payload(),
                "output_dir": str(output_dir),
                "run_meta": sanitize_mysql_analysis_payload(run_meta),
                "stdout_json": sanitize_mysql_analysis_payload(stdout_json),
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
            run = mark_task_run_success(db, run, output_text=assistant_text, output_dir=str(output_dir))
            output_files = register_output_files(db, user.id, str(output_dir))
            output_files_payload = jsonable_encoder(output_files)
            run.output_files_json = output_files_payload
            db.commit()
            append_run_event(db, runner_input.run_id, "completed", phase="completed", message="MySQL 分析任务已完成")

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
                "message": "MySQL 分析任务已完成",
                "progress_message": "MySQL 分析任务已完成",
                "runner_name": self.name,
                "task_kind": "long_job",
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
        summary = build_mysql_failure_text(phase=phase, error_message=error_message)
        sanitized_payload = sanitize_mysql_analysis_payload(raw_payload or {})
        with SessionLocal() as db:
            run = db.get(TaskRun, runner_input.run_id)
            conversation = db.get(Conversation, runner_input.conversation_id)
            if run is None:
                return
            run.duration_seconds = duration_seconds
            run.phase = phase
            run.progress_message = summary
            run.raw_payload = {
                **(run.raw_payload or {}),
                **sanitized_payload,
                "status": "failed",
                "phase": phase,
                "duration_seconds": duration_seconds,
                "task_kind": "long_job",
                "runner_name": self.name,
            }
            if run.status not in TERMINAL_RUN_STATUSES:
                run = mark_task_run_failed(db, run, summary, output_text=summary)
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
            append_run_event(db, runner_input.run_id, "failed", phase=phase, message=summary, payload=sanitized_payload)

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
                "message": summary,
                "progress_message": summary,
                "runner_name": self.name,
                "task_kind": "long_job",
                "duration_seconds": duration_seconds,
                "output_files": [],
            },
        )
