from __future__ import annotations

from pathlib import Path

from app.models.agent import Agent
from app.models.file import File


PPT_AGENT_ALIASES = {
    "ppt-generation",
    "ppt_generation",
    "pptmaster",
    "ppt-master",
    "ppt",
    "ppt 生成 agent",
    "ppt 生成",
}

PPT_GENERATION_INTENT_KEYWORDS = (
    "商品目录册",
    "产品目录册",
    "目录册ppt",
    "10-page",
    "all text in english",
    "product categories",
)

PPT_INCOMPLETE_INPUT_MARKERS = (
    "先给你",
    "稍后",
    "等下",
    "等会",
    "这个文件先收",
    "先收一下",
    "按这个做",
    "参考这个",
    "这些资料",
    "刚才资料",
)

ATTACHMENT_CONTENT_REQUIRED_MARKERS = (
    "文件内容",
    "附件内容",
    "读取",
    "解析",
    "提取",
    "根据这个excel",
    "根据这个 excel",
    "根据这份excel",
    "根据这份 excel",
    "根据这个pdf",
    "根据这个 pdf",
    "根据这份pdf",
    "根据这份 pdf",
)


def _normalize_agent_token(value: str | None) -> str:
    return (value or "").strip().lower()


def is_ppt_generation_agent(agent: Agent | None) -> bool:
    if agent is None:
        return False
    candidates = {
        _normalize_agent_token(agent.code),
        _normalize_agent_token(agent.openclaw_agent_id),
        _normalize_agent_token(agent.name),
    }
    normalized_dash = {candidate.replace("_", "-") for candidate in candidates}
    normalized_underscore = {candidate.replace("-", "_") for candidate in candidates}
    all_candidates = candidates | normalized_dash | normalized_underscore
    if all_candidates & PPT_AGENT_ALIASES:
        return True
    return any("ppt" in candidate and "生成" in candidate for candidate in candidates)


def has_ppt_generation_intent(text: str | None) -> bool:
    value = (text or "").strip().lower()
    if not value:
        return False
    if "ppt" in value or "presentation" in value or "slides" in value or "slide deck" in value:
        return True
    if any(keyword.lower() in value for keyword in PPT_GENERATION_INTENT_KEYWORDS):
        return True
    return any(action in value for action in ("生成", "做一个", "制作", "generate", "create")) and any(
        unit in value for unit in ("页", "page", "pages", "deck")
    )


def is_incomplete_ppt_input(text: str | None) -> bool:
    value = (text or "").strip().lower()
    if not value:
        return True
    has_marker = any(marker.lower() in value for marker in PPT_INCOMPLETE_INPUT_MARKERS)
    has_core_requirement = any(
        marker in value
        for marker in (
            "页",
            "page",
            "主题",
            "风格",
            "类目",
            "商品",
            "产品",
            "目录",
            "英文",
            "english",
            "company",
            "categories",
        )
    )
    if has_marker and not has_core_requirement:
        return True
    return not has_ppt_generation_intent(value) and has_marker


def requires_attachment_content(text: str | None, files: list[File]) -> bool:
    if not files:
        return False
    value = (text or "").strip().lower()
    if not value:
        return False
    if any(marker in value for marker in ATTACHMENT_CONTENT_REQUIRED_MARKERS):
        return True

    file_type_names = {Path(file.original_name or "").suffix.lower().lstrip(".") for file in files}
    file_type_names.update((file.file_type or "").strip().lower() for file in files)
    mentions_file_kind = any(kind in value for kind in ("excel", "xlsx", "xls", "pdf", "docx", "word", "表格", "文档", "文件"))
    has_known_file_kind = bool(file_type_names & {"xls", "xlsx", "pdf", "doc", "docx"})
    return mentions_file_kind and has_known_file_kind and ("内容" in value or "根据这个" in value or "根据这份" in value)
