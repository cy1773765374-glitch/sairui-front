from __future__ import annotations

from app.models.agent import Agent
from app.models.task_run import TaskRun
from app.services.daoban_service import is_daoban_agent
from app.services.mysql_analysis_service import MYSQL_ANALYSIS_RUNNER_NAME, is_mysql_analysis_agent
from app.services.runners.base import AgentRunner
from app.services.runners.daoban_job_runner import DaobanJobRunner
from app.services.runners.gateway_chat_runner import GatewayChatRunner
from app.services.runners.mysql_analysis_job_runner import MySQLAnalysisJobRunner
from app.services.runners.ppt_generation_job_runner import PPTGenerationJobRunner


class AgentRunnerRouter:
    def select_runner(self, *, run: TaskRun, agent: Agent) -> AgentRunner:
        runner_name = (run.runner_name or "").strip()
        if runner_name == DaobanJobRunner.name:
            return DaobanJobRunner()
        if runner_name == PPTGenerationJobRunner.name:
            return PPTGenerationJobRunner()
        if runner_name == MySQLAnalysisJobRunner.name:
            return MySQLAnalysisJobRunner()
        if run.run_type == "job" and is_daoban_agent(agent):
            return DaobanJobRunner()
        if run.run_type == "job" and is_mysql_analysis_agent(agent):
            return MySQLAnalysisJobRunner()
        if runner_name == MYSQL_ANALYSIS_RUNNER_NAME:
            return MySQLAnalysisJobRunner()
        return GatewayChatRunner()
