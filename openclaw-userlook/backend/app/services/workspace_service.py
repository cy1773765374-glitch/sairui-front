from __future__ import annotations

from pathlib import Path
import os

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.models.agent import Agent
from app.services.ppt_generation_service import is_ppt_generation_agent


WORKSPACE_BY_AGENT = {
    "main": "/home/cy/.openclaw/workspace",
    "recruitment": "/home/cy/.openclaw/workspace-recruitment",
    "ragagent": "/home/cy/.openclaw/workspace-ragagent",
    "spider": "/home/cy/.openclaw/workspace-spider",
    "spider_1688": "/home/cy/.openclaw/workspace-spider",
    "reminder": "/home/cy/.openclaw/workspace",
    "xingzheng": "/home/cy/.openclaw/workspace-xingzheng_a",
    "xingzheng_a": "/home/cy/.openclaw/workspace-xingzheng_a",
    "image_daoban": "/home/cy/.openclaw/workspace-image-daoban",
    "image-daoban": "/home/cy/.openclaw/workspace-image-daoban",
    "daoban": "/home/cy/.openclaw/workspace-image-daoban",
    "workspace-image-daoban": "/home/cy/.openclaw/workspace-image-daoban",
    "mysql_analysis": "/home/cy/.openclaw/workspace-huizong-ceshi",
    "huizong_ceshi": "/home/cy/.openclaw/workspace-huizong-ceshi",
    "huizong-ceshi": "/home/cy/.openclaw/workspace-huizong-ceshi",
    "PPT-Generation": "/home/cy/.openclaw/workspace-PPT-Generation",
    "ppt_generation": "/home/cy/.openclaw/workspace-PPT-Generation",
    "ppt-generation": "/home/cy/.openclaw/workspace-PPT-Generation",
    "pptmaster": "/home/cy/.openclaw/workspace-PPT-Generation",
    "ppt-master": "/home/cy/.openclaw/workspace-PPT-Generation",
    "ppt": "/home/cy/.openclaw/workspace-PPT-Generation",
}


def normalize_agent_key(value: str | None) -> str:
    return (value or "").strip().lower()


def agent_workspace_candidates(agent: Agent | None) -> list[str]:
    if agent is None:
        return []
    values = [
        normalize_agent_key(agent.code),
        normalize_agent_key(agent.openclaw_agent_id),
        normalize_agent_key(getattr(agent, "name", None)),
    ]
    expanded: list[str] = []
    for value in values:
        if not value:
            continue
        expanded.append(value)
        expanded.append(value.replace("_", "-"))
        expanded.append(value.replace("-", "_"))
    return list(dict.fromkeys(expanded))


def resolve_agent_workspace(agent: Agent | None, *, require_exists: bool = False) -> Path:
    settings = get_settings()
    explicit_ppt_workspace = os.getenv("PPT_GENERATION_WORKSPACE")
    if explicit_ppt_workspace and is_ppt_generation_agent(agent):
        workspace_value = explicit_ppt_workspace.strip()
    else:
        workspace_value = (getattr(agent, "workspace_path", None) or "").strip() if agent is not None else ""
    if not workspace_value:
        for key in agent_workspace_candidates(agent):
            workspace_value = WORKSPACE_BY_AGENT.get(key, "")
            if workspace_value:
                break
    if not workspace_value and is_ppt_generation_agent(agent):
        workspace_value = settings.ppt_generation_workspace
    if not workspace_value:
        workspace_value = settings.openclaw_default_workspace

    path = Path(workspace_value).expanduser()
    if require_exists and not path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "AGENT_WORKSPACE_MISSING",
                "message": f"Agent workspace 不存在：{path}",
                "workspace_path": str(path),
            },
        )
    return path
