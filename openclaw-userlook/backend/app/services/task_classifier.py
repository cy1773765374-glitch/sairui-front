from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.file import File
from app.models.pending_task_input import PendingTaskInput
from app.models.user import User
from app.services.daoban_service import is_daoban_agent, is_pdf_file
from app.services.pending_task_service import get_pending_task


class TaskKind(str, Enum):
    short_chat = "short_chat"
    long_job = "long_job"
    pending_input = "pending_input"


class MemoryAction(str, Enum):
    none = "none"
    save_pdf = "save_pdf"
    save_text = "save_text"
    clear_pending = "clear_pending"
    consume_pending = "consume_pending"


@dataclass(frozen=True)
class TaskClassification:
    task_kind: TaskKind
    runner: str
    reason: str
    requires_file: bool = False
    requires_text: bool = False
    memory_action: MemoryAction = MemoryAction.none
    response_message: str | None = None
    effective_content: str | None = None
    effective_file_ids: list[int] | None = None
    selected_pending_file_id: int | None = None
    pending_task: PendingTaskInput | None = None


DAOBAN_TASK_TYPE = "daoban"
LONG_JOB_KEYWORDS = (
    "生成",
    "合成",
    "导出",
    "汇总",
    "采集",
    "处理",
    "分析文件",
    "生成报告",
    "生成图片",
    "生成PDF",
    "跑一下",
    "执行",
    "批量",
    "统计",
    "图表",
    "下载",
    "整理文件",
)
CLEAR_PENDING_WORDS = {"取消", "清空", "重来", "cancel", "reset", "clear"}


def _pending_file_ids(pending: PendingTaskInput | None) -> list[int]:
    if pending is None:
        return []
    value = pending.pending_file_ids
    if isinstance(value, list):
        return [int(item) for item in value if item is not None]
    return []


def classify_task(
    db: Session,
    *,
    user: User,
    agent: Agent,
    conversation_id: int,
    content: str,
    files: list[File],
) -> TaskClassification:
    text_value = (content or "").strip()
    file_ids = [file.id for file in files]
    if is_daoban_agent(agent):
        pending = get_pending_task(
            db,
            user_id=user.id,
            conversation_id=conversation_id,
            agent_id=agent.id,
            task_type=DAOBAN_TASK_TYPE,
        )
        if text_value.lower() in CLEAR_PENDING_WORDS:
            return TaskClassification(
                task_kind=TaskKind.pending_input,
                runner="pending_input",
                reason="daoban_clear_pending",
                memory_action=MemoryAction.clear_pending,
                response_message="已清空当前待处理的刀版输入。",
                effective_content=text_value,
                effective_file_ids=file_ids,
                pending_task=pending,
            )

        pdf_files = [file for file in files if is_pdf_file(file)]
        current_pdf_file_ids = [file.id for file in pdf_files]
        pending_files = _pending_file_ids(pending)
        pending_text = (pending.pending_text or "").strip() if pending is not None else ""

        if current_pdf_file_ids and text_value:
            return TaskClassification(
                task_kind=TaskKind.long_job,
                runner="daoban_job",
                reason="daoban_pdf_and_text",
                memory_action=MemoryAction.consume_pending if pending is not None else MemoryAction.none,
                effective_content=text_value,
                effective_file_ids=file_ids,
                selected_pending_file_id=None,
                pending_task=pending,
            )

        if current_pdf_file_ids and pending_text:
            return TaskClassification(
                task_kind=TaskKind.long_job,
                runner="daoban_job",
                reason="daoban_pdf_after_pending_text",
                memory_action=MemoryAction.consume_pending,
                effective_content=pending_text,
                effective_file_ids=file_ids,
                selected_pending_file_id=None,
                pending_task=pending,
            )

        if current_pdf_file_ids:
            return TaskClassification(
                task_kind=TaskKind.pending_input,
                runner="pending_input",
                reason="daoban_pdf_only",
                requires_text=True,
                memory_action=MemoryAction.save_pdf,
                response_message="已收到刀版 PDF，请继续输入创意描述。",
                effective_content=text_value,
                effective_file_ids=file_ids,
                selected_pending_file_id=current_pdf_file_ids[-1],
                pending_task=pending,
            )

        if text_value and pending_files:
            selected_file_id = pending_files[-1]
            return TaskClassification(
                task_kind=TaskKind.long_job,
                runner="daoban_job",
                reason="daoban_text_after_pending_pdf",
                memory_action=MemoryAction.consume_pending,
                effective_content=text_value,
                effective_file_ids=[selected_file_id],
                selected_pending_file_id=selected_file_id,
                pending_task=pending,
            )

        if text_value:
            return TaskClassification(
                task_kind=TaskKind.pending_input,
                runner="pending_input",
                reason="daoban_text_only",
                requires_file=True,
                memory_action=MemoryAction.save_text,
                response_message="已记录创意描述，请上传 PDF 刀版文件。",
                effective_content=text_value,
                effective_file_ids=file_ids,
                pending_task=pending,
            )

        return TaskClassification(
            task_kind=TaskKind.pending_input,
            runner="pending_input",
            reason="daoban_empty_message",
            requires_file=True,
            requires_text=True,
            response_message="请上传 PDF 刀版文件，并输入创意描述。",
            effective_content=text_value,
            effective_file_ids=file_ids,
            pending_task=pending,
        )

    execution_mode = (agent.execution_mode or "chat").strip().lower()
    reason = "default_short_chat"
    if execution_mode in {"job", "auto"}:
        reason = "gateway_chat_until_local_runner_available"
    if file_ids and any(keyword in text_value for keyword in LONG_JOB_KEYWORDS):
        reason = "file_task_keyword_gateway_chat_until_local_runner_available"
    return TaskClassification(
        task_kind=TaskKind.short_chat,
        runner="gateway_chat",
        reason=reason,
        effective_content=text_value,
        effective_file_ids=file_ids,
    )
