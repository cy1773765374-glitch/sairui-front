from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import uuid4

from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.user import User

WEB_CHANNEL = "web_userlook"
SOURCE = "openclaw-userlook"


@dataclass(frozen=True)
class GatewaySessionIdentity:
    channel: str
    agent_id: str
    agent_code: str
    openclaw_agent_id: str
    session_key: str
    conversation_id: int
    run_id: int | None
    client_message_id: str
    idempotency_key: str
    user_id: int

    def model_dump(self) -> dict[str, object]:
        return asdict(self)


def normalize_client_message_id(client_message_id: str | None = None) -> str:
    value = (client_message_id or "").strip()
    return value[:80] if value else str(uuid4())


def build_gateway_session_key(user: User, agent: Agent, conversation: Conversation) -> str:
    openclaw_agent_id = (agent.openclaw_agent_id or "").strip() or agent.code
    return f"agent:{openclaw_agent_id}:web:{user.id}:{agent.code}:{conversation.id}"


def build_gateway_session_identity(
    user: User,
    agent: Agent,
    conversation: Conversation,
    run_id: int | None,
    client_message_id: str | None,
) -> GatewaySessionIdentity:
    normalized_client_message_id = normalize_client_message_id(client_message_id)
    openclaw_agent_id = (agent.openclaw_agent_id or "").strip() or agent.code
    idempotency_run_part = str(run_id) if run_id is not None else "pending"
    return GatewaySessionIdentity(
        channel=WEB_CHANNEL,
        agent_id=openclaw_agent_id,
        agent_code=agent.code,
        openclaw_agent_id=openclaw_agent_id,
        session_key=build_gateway_session_key(user, agent, conversation),
        conversation_id=conversation.id,
        run_id=run_id,
        client_message_id=normalized_client_message_id,
        idempotency_key=f"{SOURCE}:{idempotency_run_part}:{normalized_client_message_id}",
        user_id=user.id,
    )
