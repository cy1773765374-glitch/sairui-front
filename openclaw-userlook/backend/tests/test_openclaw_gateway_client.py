from app.models.agent import Agent, AgentRiskLevel
from app.models.conversation import Conversation
from app.models.user import User, UserRole, UserStatus
from app.services.openclaw_gateway_client import OpenClawGatewayClient


def test_build_chat_request_keeps_required_agent_route_without_extended_params() -> None:
    client = OpenClawGatewayClient(
        ws_url="ws://127.0.0.1:18789",
        token="token",
        timeout_seconds=300,
    )
    user = User(
        id=7,
        username="alice",
        password_hash="x",
        display_name="Alice",
        status=UserStatus.active,
        role=UserRole.user,
    )
    agent = Agent(
        id=3,
        code="mysql",
        name="MySQL Agent",
        openclaw_agent_id="mysql-analysis",
        risk_level=AgentRiskLevel.low,
    )
    conversation = Conversation(
        id=11,
        user_id=user.id,
        agent_id=agent.id,
        title="MySQL",
        session_key="web:7:mysql:11",
    )

    payload = client._build_chat_request(
        user=user,
        agent=agent,
        conversation=conversation,
        content="who are you",
        file_ids=[],
        files=[],
        run_id=59,
        output_dir="/data/openclaw-userlook/outputs/7/20260603/run_59",
        client_message_id="client-1",
        gateway_session_key="agent:mysql-analysis:web:7:mysql:11",
        idempotency_key="openclaw-userlook:59:client-1",
    )

    assert payload["method"] == "chat.send"
    params = payload["params"]
    assert params["agentId"] == "mysql-analysis"
    assert params["sessionKey"] == "agent:mysql-analysis:web:7:mysql:11"
    assert params["message"].endswith("\n\nwho are you")
    assert "run_id=59" in params["message"]
    assert "client_message_id=client-1" in params["message"]
    assert params["idempotencyKey"] == "openclaw-userlook:59:client-1"

    assert "metadata" not in params
    assert "context" not in params
    assert "channel" not in params
    assert "runId" not in params
    assert "clientMessageId" not in params
