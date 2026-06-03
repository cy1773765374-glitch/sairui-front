from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import websockets
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.models.agent import Agent, AgentRiskLevel  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.user import User, UserRole, UserStatus  # noqa: E402
from app.services.openclaw_gateway_client import (  # noqa: E402
    GatewayDebugCollector,
    OpenClawGatewayClient,
    sanitize_gateway_payload,
)


VARIANTS = (
    "current_chat_send",
    "deliver_true",
    "deliver_true_agentId",
    "deliver_true_agent_id",
    "legacy_action",
)


def make_user() -> User:
    return User(
        id=0,
        username="probe",
        password_hash="probe",
        display_name="Gateway Probe",
        status=UserStatus.active,
        role=UserRole.user,
    )


def make_agent(agent_id: str) -> Agent:
    return Agent(
        id=0,
        code=agent_id,
        name=agent_id,
        openclaw_agent_id=agent_id,
        risk_level=AgentRiskLevel.low,
    )


def make_conversation(agent_id: str) -> Conversation:
    return Conversation(
        id=0,
        user_id=0,
        agent_id=0,
        title=f"probe:{agent_id}",
        session_key=f"probe:{agent_id}:{int(time.time())}",
    )


def base_chat_send_request(
    client: OpenClawGatewayClient,
    *,
    agent_id: str,
    message: str,
    timeout: int,
    variant: str,
) -> dict[str, Any]:
    user = make_user()
    agent = make_agent(agent_id)
    conversation = make_conversation(agent_id)
    payload = client._build_chat_request(
        user=user,
        agent=agent,
        conversation=conversation,
        content=message,
        file_ids=[],
        files=[],
        run_id=None,
        output_dir=None,
        client_message_id=f"probe-{int(time.time() * 1000)}",
        gateway_session_key=None,
        idempotency_key=None,
    )
    params = payload["params"]
    base_keys = {"sessionKey", "message", "deliver", "timeoutMs", "idempotencyKey"}
    stripped = {key: value for key, value in params.items() if key in base_keys}
    stripped["timeoutMs"] = timeout * 1000

    if variant == "current_chat_send":
        stripped["deliver"] = False
    elif variant == "deliver_true":
        stripped["deliver"] = True
    elif variant == "deliver_true_agentId":
        stripped["deliver"] = True
        stripped["agentId"] = agent_id
    elif variant == "deliver_true_agent_id":
        stripped["deliver"] = True
        stripped["agent_id"] = agent_id
    else:
        raise ValueError(f"unsupported chat.send variant: {variant}")

    payload["params"] = stripped
    return payload


def legacy_action_request(*, agent_id: str, message: str, timeout: int) -> dict[str, Any]:
    return {
        "type": "chat",
        "action": "chat",
        "stream": True,
        "agent_id": agent_id,
        "session_key": f"probe:{agent_id}:{int(time.time())}",
        "timeoutMs": timeout * 1000,
        "user": {
            "id": 0,
            "username": "probe",
            "display_name": "Gateway Probe",
            "role": "user",
        },
        "message": {
            "role": "user",
            "content": message,
            "file_ids": [],
        },
    }


def build_request(
    client: OpenClawGatewayClient,
    *,
    agent_id: str,
    message: str,
    timeout: int,
    variant: str,
) -> dict[str, Any]:
    if variant == "legacy_action":
        return legacy_action_request(agent_id=agent_id, message=message, timeout=timeout)
    return base_chat_send_request(
        client,
        agent_id=agent_id,
        message=message,
        timeout=timeout,
        variant=variant,
    )


def classify_frame(client: OpenClawGatewayClient, frame: Any) -> tuple[str, str | None]:
    if isinstance(frame, dict) and client.is_global_gateway_event(frame):
        return "global_ignored", None
    event = client._parse_gateway_payload(frame)
    if event.type == "delta":
        return "parsed_delta", event.content
    if event.type == "done":
        return "parsed_done", event.content
    if event.type == "error":
        return "parsed_error", event.content
    return "parsed_run_status", event.status


async def run_variant(
    client: OpenClawGatewayClient,
    *,
    agent_id: str,
    message: str,
    timeout: int,
    variant: str,
) -> dict[str, Any]:
    request_payload = build_request(
        client,
        agent_id=agent_id,
        message=message,
        timeout=timeout,
        variant=variant,
    )
    frames: list[dict[str, Any]] = []
    flags = {
        "assistant_delta": False,
        "done": False,
        "success": False,
        "error": False,
    }
    started_at = time.monotonic()

    async with websockets.connect(
        client.ws_url,
        additional_headers=client._build_headers(),
        open_timeout=5,
        close_timeout=5,
        ping_interval=20,
        ping_timeout=20,
    ) as gateway_ws:
        await client._connect_gateway(gateway_ws)
        await gateway_ws.send(json.dumps(request_payload, ensure_ascii=False))
        while time.monotonic() - started_at < timeout and len(frames) < 50:
            try:
                raw_frame = await asyncio.wait_for(gateway_ws.recv(), timeout=1)
            except asyncio.TimeoutError:
                continue
            frame = client._decode_json_frame(raw_frame)
            classification, parsed_value = classify_frame(client, frame)
            if classification == "parsed_delta":
                flags["assistant_delta"] = True
            if classification == "parsed_done":
                flags["done"] = True
                flags["success"] = True
            if classification == "parsed_error":
                flags["error"] = True
            frames.append(
                {
                    "classification": classification,
                    "parsed_value": parsed_value,
                    "frame": sanitize_gateway_payload(frame),
                }
            )
            if flags["done"] or flags["error"]:
                break

    return {
        "variant": variant,
        "request": sanitize_gateway_payload(request_payload),
        "frames": frames,
        "flags": flags,
        "received_assistant_output": flags["assistant_delta"] or flags["success"],
    }


async def probe(args: argparse.Namespace) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    settings = get_settings()
    variants = VARIANTS if args.protocol_variant == "auto" else (args.protocol_variant,)
    client = OpenClawGatewayClient(
        ws_url=settings.openclaw_gateway_ws_url,
        token=settings.openclaw_gateway_token,
        password=settings.openclaw_gateway_password,
        timeout_seconds=args.timeout or settings.openclaw_gateway_timeout_seconds,
        deliver=settings.openclaw_gateway_deliver,
        max_concurrency=1,
    )

    results: list[dict[str, Any]] = []
    for variant in variants:
        result = await run_variant(
            client,
            agent_id=args.agent,
            message=args.message,
            timeout=args.timeout,
            variant=variant,
        )
        results.append(result)
        if result["received_assistant_output"]:
            break

    return {
        "agent": args.agent,
        "message": args.message,
        "timeout": args.timeout,
        "ws_url": settings.openclaw_gateway_ws_url,
        "results": results,
        "success": any(result["received_assistant_output"] for result in results),
    }


def save_result(result: dict[str, Any]) -> Path:
    output_dir = ROOT / "probe-results"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"openclaw_gateway_probe_{result['agent']}_{int(time.time())}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe OpenClaw Gateway chat protocol.")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--protocol-variant", choices=("auto", *VARIANTS), default="auto")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(probe(args))
    except Exception as exc:
        result = {
            "agent": args.agent,
            "message": args.message,
            "timeout": args.timeout,
            "success": False,
            "error": str(exc),
        }
    path = save_result(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"saved={path}")
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
