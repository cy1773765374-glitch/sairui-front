from __future__ import annotations

import asyncio

from app.services.runners.base import AgentRunner, RunnerInput


class GatewayChatRunner(AgentRunner):
    name = "gateway_chat"

    async def run(self, runner_input: RunnerInput, cancel_event: asyncio.Event) -> None:
        from app.services.task_executor import _execute_gateway_chat_run

        await _execute_gateway_chat_run(
            run_id=runner_input.run_id,
            user_id=runner_input.user_id,
            agent_id=runner_input.agent_id,
            conversation_id=runner_input.conversation_id,
            content=runner_input.content,
            file_ids=runner_input.file_ids,
            gateway_files=[],
            cancel_event=cancel_event,
        )
