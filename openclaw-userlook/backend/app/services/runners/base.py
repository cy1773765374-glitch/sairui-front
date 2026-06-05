from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class RunnerInput:
    run_id: int
    user_id: int
    agent_id: int
    conversation_id: int
    content: str
    file_ids: list[int]


class AgentRunner:
    name = "base"

    async def run(self, runner_input: RunnerInput, cancel_event: asyncio.Event) -> None:
        raise NotImplementedError
