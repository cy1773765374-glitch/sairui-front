from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.models.agent import Agent, AgentRiskLevel


DEFAULT_AGENTS = [
    {
        "code": "main",
        "name": "主助理 Agent",
        "description": "通用问题处理与日常辅助 Agent。",
        "category": "general",
        "openclaw_agent_id": "main",
        "enabled": True,
        "risk_level": AgentRiskLevel.medium,
        "support_files": True,
        "support_images": True,
        "workspace_path": "/home/cy/.openclaw/workspace",
        "execution_mode": "chat",
    },
    {
        "code": "mysql_analysis",
        "name": "MySQL 分析 Agent",
        "description": "用于数据库分析与查询辅助的 Agent。",
        "category": "data",
        "openclaw_agent_id": "huizong-ceshi",
        "enabled": True,
        "risk_level": AgentRiskLevel.high,
        "support_files": False,
        "support_images": False,
        "workspace_path": "/home/cy/.openclaw/workspace-huizong-ceshi",
        "execution_mode": "auto",
    },
    {
        "code": "ppt_generation",
        "name": "PPT 生成 Agent",
        "description": "用于演示文稿内容整理与生成的文档 Agent。",
        "category": "document",
        "openclaw_agent_id": "ppt-generation",
        "enabled": True,
        "risk_level": AgentRiskLevel.medium,
        "support_files": True,
        "support_images": True,
        "workspace_path": "/home/cy/.openclaw/workspace",
        "execution_mode": "auto",
    },
    {
        "code": "image_daoban",
        "name": "刀版合成 Agent",
        "description": "用于图片和刀版合成处理的设计 Agent。",
        "category": "design",
        "openclaw_agent_id": "image-daoban",
        "enabled": True,
        "risk_level": AgentRiskLevel.medium,
        "support_files": True,
        "support_images": True,
        "workspace_path": "/home/cy/.openclaw/workspace-image-daoban",
        "execution_mode": "job",
    },
    {
        "code": "spider_1688",
        "name": "1688 采集 Agent",
        "description": "外部服务器 Agent，当前服务器暂未接入。",
        "category": "external",
        "openclaw_agent_id": "spider",
        "enabled": False,
        "risk_level": AgentRiskLevel.high,
        "support_files": False,
        "support_images": False,
        "workspace_path": "/home/cy/.openclaw/workspace-spider",
        "execution_mode": "auto",
    },
    {
        "code": "xingzheng",
        "name": "行政快递汇总 Agent",
        "description": "外部服务器 Agent，当前服务器暂未接入。",
        "category": "external",
        "openclaw_agent_id": "xingzheng_a",
        "enabled": False,
        "risk_level": AgentRiskLevel.medium,
        "support_files": True,
        "support_images": True,
        "workspace_path": "/home/cy/.openclaw/workspace-xingzheng_a",
        "execution_mode": "auto",
    },
]


def seed_agents(db: Session) -> list[Agent]:
    agents: list[Agent] = []
    for agent_data in DEFAULT_AGENTS:
        agent = db.scalar(select(Agent).where(Agent.code == agent_data["code"]))
        if agent is None:
            agent = Agent(**agent_data)
            db.add(agent)
        else:
            for field, value in agent_data.items():
                if field != "code":
                    setattr(agent, field, value)
        agents.append(agent)

    db.commit()
    for agent in agents:
        db.refresh(agent)
    return agents


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_agents(db)


if __name__ == "__main__":
    main()
    print("Default agents ensured.")
