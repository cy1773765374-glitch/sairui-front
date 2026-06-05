from __future__ import annotations

from app.models.agent import Agent
from app.models.task_run import TaskRun
from app.services.daoban_service import is_daoban_agent
from app.services.runners.base import AgentRunner
from app.services.runners.daoban_job_runner import DaobanJobRunner
from app.services.runners.gateway_chat_runner import GatewayChatRunner


class AgentRunnerRouter:
    def select_runner(self, *, run: TaskRun, agent: Agent) -> AgentRunner:
        runner_name = (run.runner_name or "").strip()
        if runner_name == DaobanJobRunner.name:
            return DaobanJobRunner()
        if run.run_type == "job" and is_daoban_agent(agent):
            return DaobanJobRunner()
        return GatewayChatRunner()
