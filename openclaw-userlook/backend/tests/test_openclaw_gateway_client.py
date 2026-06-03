import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.models.agent import Agent, AgentRiskLevel
from app.models.conversation import Conversation
from app.models.user import User, UserRole, UserStatus
from app.services.gateway_session import build_gateway_session_identity
from app.services.openclaw_gateway_client import OpenClawGatewayClient
from app.services.openclaw_gateway_client import OpenClawGatewayConnectionError


def make_user() -> User:
    return User(
        id=7,
        username="alice",
        password_hash="x",
        display_name="Alice",
        status=UserStatus.active,
        role=UserRole.user,
    )


def make_agent() -> Agent:
    return Agent(
        id=3,
        code="mysql",
        name="MySQL Agent",
        openclaw_agent_id="mysql-analysis",
        risk_level=AgentRiskLevel.low,
    )


def make_conversation() -> Conversation:
    return Conversation(
        id=11,
        user_id=7,
        agent_id=3,
        title="MySQL",
        session_key="web:7:mysql:11",
    )


class OpenClawGatewayClientTest(unittest.TestCase):
    def test_build_gateway_session_identity_isolates_web_agent_conversation(self) -> None:
        identity = build_gateway_session_identity(
            make_user(),
            make_agent(),
            make_conversation(),
            59,
            "client-1",
        )

        self.assertEqual(identity.channel, "web_userlook")
        self.assertEqual(identity.agent_id, "mysql-analysis")
        self.assertEqual(identity.agent_code, "mysql")
        self.assertEqual(identity.openclaw_agent_id, "mysql-analysis")
        self.assertEqual(identity.session_key, "agent:mysql-analysis:web:7:mysql:11")
        self.assertEqual(identity.client_message_id, "client-1")
        self.assertEqual(identity.idempotency_key, "openclaw-userlook:59:client-1")

    def test_build_chat_request_uses_gateway_compatible_params_and_keeps_identity_context(self) -> None:
        client = OpenClawGatewayClient(
            ws_url="ws://127.0.0.1:18789",
            token="token",
            timeout_seconds=300,
        )

        payload = client._build_chat_request(
            user=make_user(),
            agent=make_agent(),
            conversation=make_conversation(),
            content="who are you",
            file_ids=[],
            files=[],
            run_id=59,
            output_dir="/data/openclaw-userlook/outputs/7/20260603/run_59",
            client_message_id="client-1",
            gateway_session_key="agent:mysql-analysis:web:7:mysql:11",
            idempotency_key="openclaw-userlook:59:client-1",
        )

        self.assertEqual(payload["method"], "chat.send")
        params = payload["params"]
        self.assertEqual(set(params), {"sessionKey", "message", "deliver", "timeoutMs", "idempotencyKey"})
        self.assertEqual(params["deliver"], True)
        self.assertEqual(params["sessionKey"], "agent:mysql-analysis:web:7:mysql:11")
        self.assertTrue(params["message"].endswith("\n\nwho are you"))
        self.assertIn("channel=web_userlook", params["message"])
        self.assertIn("agent_code=mysql", params["message"])
        self.assertIn("openclaw_agent_id=mysql-analysis", params["message"])
        self.assertIn("run_id=59", params["message"])
        self.assertIn("client_message_id=client-1", params["message"])
        self.assertEqual(params["idempotencyKey"], "openclaw-userlook:59:client-1")

    def test_gateway_frame_attribution_rejects_mismatched_run_context(self) -> None:
        client = OpenClawGatewayClient(ws_url="ws://127.0.0.1:18789")
        current = {
            "run_id": 59,
            "request_id": "chat-59",
            "session_key": "agent:mysql-analysis:web:7:mysql:11",
            "conversation_id": 11,
            "client_message_id": "client-1",
            "idempotency_key": "openclaw-userlook:59:client-1",
        }

        self.assertTrue(
            client._is_frame_for_current_run(
                {"type": "event", "event": "assistant_delta", "runId": 59, "clientMessageId": "client-1"},
                **current,
            )
        )
        self.assertFalse(
            client._is_frame_for_current_run(
                {"type": "event", "event": "assistant_delta", "runId": 60, "clientMessageId": "client-1"},
                **current,
            )
        )
        self.assertFalse(
            client._is_frame_for_current_run(
                {"type": "event", "event": "assistant_delta", "runId": 59, "clientMessageId": "other-client"},
                **current,
            )
        )
        self.assertTrue(
            client._is_frame_for_current_run(
                {
                    "type": "event",
                    "event": "chat",
                    "payload": {
                        "runId": "openclaw-userlook:59:client-1",
                        "sessionKey": "agent:mysql-analysis:web:7:mysql:11",
                        "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
                    },
                },
                **current,
            )
        )

    def test_chat_send_guard_rejects_structured_agent_id_param(self) -> None:
        client = OpenClawGatewayClient(ws_url="ws://127.0.0.1:18789")

        with self.assertRaisesRegex(Exception, "unexpected agentId"):
            client._validate_chat_send_request(
                {
                    "type": "req",
                    "id": "chat-59",
                    "method": "chat.send",
                    "params": {
                        "sessionKey": "agent:mysql-analysis:web:7:mysql:11",
                        "message": "who are you",
                        "deliver": True,
                        "timeoutMs": 300000,
                        "idempotencyKey": "openclaw-userlook:59:client-1",
                        "agentId": "mysql-analysis",
                    },
                }
            )

    def test_gateway_context_exposes_generated_client_message_id(self) -> None:
        client = OpenClawGatewayClient(ws_url="ws://127.0.0.1:18789")
        payload = client._build_chat_request(
            user=make_user(),
            agent=make_agent(),
            conversation=make_conversation(),
            content="who are you",
            file_ids=[],
            files=[],
            run_id=59,
            output_dir=None,
            client_message_id=None,
            gateway_session_key=None,
            idempotency_key=None,
        )

        message = payload["params"]["message"]
        client_message_id = client._extract_gateway_context_value(message, "client_message_id")
        self.assertIsNotNone(client_message_id)
        self.assertIn(f"client_message_id={client_message_id}", message)
        self.assertTrue(payload["params"]["idempotencyKey"].endswith(f":{client_message_id}"))

    def test_build_chat_request_includes_clean_attachments_when_files_are_present(self) -> None:
        client = OpenClawGatewayClient(ws_url="ws://127.0.0.1:18789")
        payload = client._build_chat_request(
            user=make_user(),
            agent=make_agent(),
            conversation=make_conversation(),
            content="summarize this",
            file_ids=[1, 2],
            files=[
                {
                    "path": "C:\\data\\uploads\\report.xlsx",
                    "file_type": "xlsx",
                    "file_size": 1234,
                },
                {
                    "stored_path": "/data/uploads/readme.md",
                    "original_name": "readme.md",
                    "file_type": None,
                    "file_size": None,
                },
            ],
            run_id=59,
            output_dir=None,
            client_message_id="client-1",
            gateway_session_key=None,
            idempotency_key=None,
        )

        self.assertIn("attachments", payload["params"])
        self.assertEqual(
            payload["params"]["attachments"],
            [
                {
                    "name": "report.xlsx",
                    "path": "C:\\data\\uploads\\report.xlsx",
                    "source": "openclaw-userlook",
                    "mimeType": "xlsx",
                    "size": 1234,
                },
                {
                    "name": "readme.md",
                    "path": "/data/uploads/readme.md",
                    "source": "openclaw-userlook",
                },
            ],
        )

    def test_ack_only_response_is_run_status_not_done(self) -> None:
        client = OpenClawGatewayClient(ws_url="ws://127.0.0.1:18789")

        event = client._parse_gateway_payload(
            {"type": "res", "id": "chat-59", "ok": True, "payload": {"status": "success"}}
        )

        self.assertEqual(event.type, "run_status")
        self.assertEqual(event.status, "running")

    def test_parse_assistant_delta_done_error_and_nested_text(self) -> None:
        client = OpenClawGatewayClient(ws_url="ws://127.0.0.1:18789")

        delta = client._parse_gateway_payload(
            {"type": "event", "event": "assistant_delta", "payload": {"delta": "hello"}}
        )
        done = client._parse_gateway_payload(
            {"type": "event", "event": "done", "payload": {"answer": {"content": "final"}}}
        )
        error = client._parse_gateway_payload(
            {"type": "event", "event": "error", "payload": {"message": "bad gateway"}}
        )

        self.assertEqual(delta.type, "delta")
        self.assertEqual(delta.content, "hello")
        self.assertEqual(done.type, "done")
        self.assertEqual(done.content, "final")
        self.assertEqual(error.type, "error")
        self.assertEqual(error.status, "failed")
        self.assertEqual(error.content, "bad gateway")


class OpenClawGatewayClientStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_chat_sends_gateway_compatible_payload(self) -> None:
        client = OpenClawGatewayClient(
            ws_url="ws://127.0.0.1:18789",
            token="token",
            timeout_seconds=300,
        )
        fake_ws = FakeGatewayWebSocket(
            [
                {"type": "res", "id": "chat-59", "ok": True, "payload": {"status": "success"}},
                {"type": "event", "event": "assistant_delta", "payload": {"delta": "ok"}},
                {"type": "event", "event": "done", "payload": {"status": "success"}},
            ]
        )

        with patch("app.services.openclaw_gateway_client.websockets.connect", return_value=FakeGatewayConnection(fake_ws)):
            client._connect_gateway = AsyncMock(return_value=None)
            events = [
                event
                async for event in client.stream_chat(
                    user=make_user(),
                    agent=make_agent(),
                    conversation=make_conversation(),
                    content="who are you",
                    file_ids=[],
                    files=[],
                    run_id=59,
                    output_dir="/data/openclaw-userlook/outputs/7/20260603/run_59",
                    client_message_id="client-1",
                    gateway_session_key="agent:mysql-analysis:web:7:mysql:11",
                    idempotency_key="openclaw-userlook:59:client-1",
                )
            ]

        self.assertEqual([event.type for event in events], ["run_status", "delta", "done"])
        self.assertEqual(events[1].content, "ok")
        sent_payload = json.loads(fake_ws.sent_messages[0])
        self.assertEqual(sent_payload["method"], "chat.send")
        self.assertEqual(sent_payload["params"]["deliver"], True)
        self.assertEqual(set(sent_payload["params"]), {"sessionKey", "message", "deliver", "timeoutMs", "idempotencyKey"})

    async def test_stream_chat_records_health_frame_as_debug_only(self) -> None:
        client = OpenClawGatewayClient(ws_url="ws://127.0.0.1:18789", token="token", timeout_seconds=300)
        fake_ws = FakeGatewayWebSocket(
            [
                {"type": "event", "event": "health", "payload": {"status": "ok"}},
                {"type": "event", "event": "assistant_delta", "payload": {"delta": "hello"}},
                {"type": "event", "event": "done", "payload": {"status": "success"}},
            ]
        )

        with patch("app.services.openclaw_gateway_client.websockets.connect", return_value=FakeGatewayConnection(fake_ws)):
            client._connect_gateway = AsyncMock(return_value=None)
            events = [
                event
                async for event in client.stream_chat(
                    user=make_user(),
                    agent=make_agent(),
                    conversation=make_conversation(),
                    content="who are you",
                    file_ids=[],
                    files=[],
                    run_id=59,
                    output_dir=None,
                    client_message_id="client-1",
                    gateway_session_key="agent:mysql-analysis:web:7:mysql:11",
                    idempotency_key="openclaw-userlook:59:client-1",
                )
            ]

        self.assertEqual([event.type for event in events], ["delta", "done"])
        debug_events = events[0].gateway_debug_events or []
        self.assertTrue(any(item["classification"] == "global_ignored" for item in debug_events))

    async def test_stream_chat_times_out_when_no_first_assistant_output_arrives(self) -> None:
        client = OpenClawGatewayClient(ws_url="ws://127.0.0.1:18789", token="token", timeout_seconds=300)
        fake_ws = FakeGatewayWebSocket(
            [
                {"type": "event", "event": "tick", "payload": {"ts": 1}},
            ]
        )

        with patch("app.services.openclaw_gateway_client.websockets.connect", return_value=FakeGatewayConnection(fake_ws)):
            client._connect_gateway = AsyncMock(return_value=None)
            with self.assertRaisesRegex(OpenClawGatewayConnectionError, "first assistant output timed out") as raised:
                [
                    event
                    async for event in client.stream_chat(
                        user=make_user(),
                        agent=make_agent(),
                        conversation=make_conversation(),
                        content="who are you",
                        file_ids=[],
                        files=[],
                        run_id=59,
                        output_dir=None,
                        client_message_id="client-1",
                        gateway_session_key="agent:mysql-analysis:web:7:mysql:11",
                        idempotency_key="openclaw-userlook:59:client-1",
                        first_token_timeout_seconds=1,
                        recv_tick_seconds=1,
                    )
                ]

        debug_events = raised.exception.gateway_debug_events
        self.assertTrue(any(item["classification"] == "parsed_run_status" for item in debug_events))


class FakeGatewayConnection:
    def __init__(self, websocket: "FakeGatewayWebSocket") -> None:
        self.websocket = websocket

    async def __aenter__(self) -> "FakeGatewayWebSocket":
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class FakeGatewayWebSocket:
    def __init__(self, frames: list[dict[str, object]]) -> None:
        self.sent_messages: list[str] = []
        self.frames = list(frames)

    async def send(self, message: str) -> None:
        self.sent_messages.append(message)

    async def recv(self) -> str:
        if not self.frames:
            await asyncio.sleep(0)
            raise asyncio.TimeoutError
        return json.dumps(self.frames.pop(0))

    async def close(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
