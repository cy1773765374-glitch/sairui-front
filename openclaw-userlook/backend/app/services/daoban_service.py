from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.agent import Agent
from app.models.file import File
from app.models.task_run import TaskRun
from app.services.file_service import files_to_gateway_payload

DAOBAN_AGENT_ALIASES = {
    "image-daoban",
    "image_daoban",
    "daoban",
    "workspace-image-daoban",
    "刀版合成",
}
DAOBAN_OUTPUT_ROOT = "/data/share/yaq/test"
DAOBAN_EXPECTED_OUTPUTS = [
    "out.pdf",
    "out.png",
    "report.json",
    "qc_report.json",
    "layout_plan.json",
    "preflight_report.json",
    "ai_handoff/out_ai.pdf",
]

logger = logging.getLogger(__name__)


def _normalize_agent_token(value: str | None) -> str:
    return (value or "").strip().lower()


def is_daoban_agent(agent: Agent | None) -> bool:
    if agent is None:
        return False
    candidates = {
        _normalize_agent_token(agent.code),
        _normalize_agent_token(agent.openclaw_agent_id),
        _normalize_agent_token(agent.name),
    }
    normalized_dash = {candidate.replace("_", "-") for candidate in candidates}
    if (candidates | normalized_dash) & DAOBAN_AGENT_ALIASES:
        return True
    return any("刀版合成" in candidate for candidate in candidates)


def is_pdf_file(file: File) -> bool:
    mime_type = (file.mime_type or "").strip().lower()
    file_type = (file.file_type or "").strip().lower()
    suffix = Path(file.original_name or "").suffix.lower()
    return mime_type == "application/pdf" or file_type == "pdf" or suffix == ".pdf"


def require_daoban_pdf(files: list[File]) -> File:
    for file in files:
        if is_pdf_file(file):
            return file
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "code": "DAOBAN_PDF_REQUIRED",
            "message": "刀版合成 Agent 需要上传 PDF 刀版文件",
            "detail": "刀版合成 Agent 需要上传 PDF 刀版文件",
        },
    )


def _safe_workspace_filename(file: File) -> str:
    original_name = Path(file.original_name or "").name.strip()
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", original_name).strip(" .")
    if not name:
        name = file.stored_name or f"file-{file.id}.{file.file_type or 'dat'}"
    return name


def _workspace_file_missing(file_id: int | None = None) -> HTTPException:
    detail: dict[str, object] = {
        "code": "DAOBAN_WORKSPACE_FILE_MISSING",
        "message": "刀版文件未同步到 OpenClaw 工作区，请重新上传",
        "detail": "刀版文件未同步到 OpenClaw 工作区，请重新上传",
    }
    if file_id is not None:
        detail["file_id"] = file_id
    return HTTPException(status_code=status.HTTP_410_GONE, detail=detail)


def build_daoban_payload(
    *,
    run: TaskRun,
    content: str,
    files: list[File],
    pdf_file: File,
) -> dict[str, object]:
    workspace = get_settings().openclaw_daoban_workspace
    gateway_files = files_to_gateway_payload(files, prefer_workspace_path=True)
    pdf_path = pdf_file.workspace_path
    if not pdf_path or not Path(pdf_path).expanduser().is_file():
        raise _workspace_file_missing(pdf_file.id)
    return {
        "file_ids": [file.id for file in files],
        "files": gateway_files,
        "daoban": {
            "workspace": workspace,
            "pdf_path": pdf_path,
            "prompt": content,
            "job_label": content,
            "output_root": DAOBAN_OUTPUT_ROOT,
            "expected_outputs": DAOBAN_EXPECTED_OUTPUTS,
        },
    }


def sync_daoban_files_to_workspace(
    db: Session,
    *,
    run: TaskRun,
    agent: Agent,
    content: str,
    files: list[File],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    pdf_file = require_daoban_pdf(files)
    workspace_root = Path(get_settings().openclaw_daoban_workspace).expanduser()
    input_dir = workspace_root / "data" / "input" / "userlook" / f"run-{run.id}"
    try:
        input_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("[daoban-file-sync] run_id=%s workspace_create_failed path=%s", run.id, input_dir)
        raise _workspace_file_missing(None) from exc

    used_names: set[str] = set()
    for file in files:
        source_path = Path(file.stored_path).expanduser().resolve()
        if not source_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={
                    "code": "FILE_CONTENT_MISSING",
                    "message": "上传文件内容不存在，请重新上传",
                    "detail": "上传文件内容不存在，请重新上传",
                    "file_id": file.id,
                },
            )

        target_name = _safe_workspace_filename(file)
        if target_name in used_names or (input_dir / target_name).exists():
            target_name = f"{file.id}-{target_name}"
        used_names.add(target_name)
        target_path = input_dir / target_name
        try:
            shutil.copy2(source_path, target_path)
        except OSError as exc:
            logger.warning("[daoban-file-sync] run_id=%s file_id=%s copy_failed target=%s", run.id, file.id, target_path)
            raise _workspace_file_missing(file.id) from exc

        file.workspace_path = str(target_path)
        file.agent_code = agent.code
        logger.info("[daoban-file-sync] run_id=%s file_id=%s workspace_path=%s", run.id, file.id, file.workspace_path)

    db.flush()
    payload = build_daoban_payload(run=run, content=content, files=files, pdf_file=pdf_file)
    return payload["files"], payload


def build_daoban_gateway_message(content: str, files: list[dict[str, object]]) -> str:
    pdf_file = next(
        (
            file
            for file in files
            if str(file.get("mime_type") or "").lower() == "application/pdf"
            or str(file.get("file_type") or "").lower() == "pdf"
            or str(file.get("name") or file.get("original_name") or "").lower().endswith(".pdf")
        ),
        None,
    )
    pdf_path = str((pdf_file or {}).get("workspace_path") or (pdf_file or {}).get("path") or "")
    workspace = get_settings().openclaw_daoban_workspace
    if not pdf_path:
        return content
    return "\n".join(
        [
            "用户需求：",
            content,
            "",
            "刀版 PDF 路径：",
            pdf_path,
            "",
            "请在 workspace-image-daoban 中执行刀版合成流程。",
            "要求：",
            "1. 使用 scripts/run_daoban_job.py。",
            "2. 使用上传的 PDF 作为 --pdf。",
            "3. 使用用户需求作为 --prompt。",
            "4. 使用 --clip-mode shape。",
            "5. 使用 --dieline-source auto。",
            "6. 使用 --export-mode both。",
            "7. 使用 --layout-mode shape-aware。",
            "8. 启用 ai_handoff。",
            f"9. 输出目录使用 {DAOBAN_OUTPUT_ROOT}。",
            "10. 生成完成后返回 out.pdf、out.png、report.json、qc_report.json、ai_handoff/out_ai.pdf 路径。",
            "",
            "推荐命令：",
            f"cd {workspace}",
            "source .venv/bin/activate",
            "python scripts/run_daoban_job.py \\",
            f'  --pdf "{pdf_path}" \\',
            f'  --prompt "{content}" \\',
            f'  --job-label "{content}" \\',
            "  --clip-mode shape \\",
            "  --dieline-source auto \\",
            "  --export-mode both \\",
            "  --layout-mode shape-aware \\",
            "  --preflight-mode warn \\",
            "  --ai-handoff",
        ]
    )
