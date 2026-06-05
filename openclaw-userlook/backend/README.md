# openclaw-userlook backend

Phase 07 keeps the browser-facing FastAPI WebSocket chat API from Phase 06 and adds TaskRun records, long-running status updates, user-isolated uploads, output file registration, and authenticated downloads. `MOCK_OPENCLAW=true` keeps the mock stream available; `MOCK_OPENCLAW=false` sends chat requests from FastAPI to OpenClaw Gateway over WebSocket.

## Requirements

- Python 3.12

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Create the MySQL database:

```sql
CREATE DATABASE openclaw_userlook CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Set `DATABASE_URL` in `.env`:

```text
DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/openclaw_userlook?charset=utf8mb4
```

Initialize tables:

```bash
python -m app.init_db
```

This also creates the default admin user when `DEFAULT_ADMIN_USERNAME` does not exist and seeds the preset Agents.

For existing Phase 10 databases, the backend runs the Phase 11 and Phase 12 idempotent migrations during startup. They can also be run manually after `app.init_db`:

```bash
python -m app.migrations.phase11_task_run_lifecycle
python -m app.migrations.phase12_streaming_persistence
```

The migrations add task lifecycle fields, `messages.run_id`, and `task_runs.raw_payload`, expand `task_runs.status`, and are safe to run repeatedly. They do not delete existing data.

Preset Agents can also be initialized independently:

```bash
python -m app.seed_agents
```

## Run

```bash
uvicorn app.main:app --host 127.0.0.1 --port 10009
```

## Health Check

```bash
curl http://127.0.0.1:10009/api/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "openclaw-userlook-backend"
}
```

Database health check:

```bash
curl http://127.0.0.1:10009/api/health/db
```

Expected response when MySQL is reachable:

```json
{
  "status": "ok",
  "database": "connected"
}
```

## Authentication

Register a user:

```bash
curl -X POST http://127.0.0.1:10009/api/auth/register ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"zhangsan\",\"password\":\"Admin@123456\",\"display_name\":\"张三\"}"
```

Web username/password registration creates a `pending` normal user. An admin must approve the user before login.

Login:

```bash
curl -X POST http://127.0.0.1:10009/api/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"Admin@123456\"}"
```

Admin endpoints require `Authorization: Bearer <token>`:

- `GET /api/admin/users`
- `POST /api/admin/users/{user_id}/approve`
- `POST /api/admin/users/{user_id}/disable`

## Agents

Authenticated Agent endpoints:

- `GET /api/agents`
- `GET /api/agents/{agent_id}`

Admin Agent endpoints:

- `GET /api/admin/agents`
- `POST /api/admin/agents/{agent_id}/enable`
- `POST /api/admin/agents/{agent_id}/disable`
- `POST /api/admin/agents/{agent_id}/permissions`

Grant an Agent to all normal users:

```bash
curl -X POST http://127.0.0.1:10009/api/admin/agents/main/permissions ^
  -H "Authorization: Bearer <token>" ^
  -H "Content-Type: application/json" ^
  -d "{\"role\":\"user\"}"
```

Grant an Agent to one user:

```bash
curl -X POST http://127.0.0.1:10009/api/admin/agents/main/permissions ^
  -H "Authorization: Bearer <token>" ^
  -H "Content-Type: application/json" ^
  -d "{\"user_id\":2}"
```

## Environment

- `OPENCLAW_GATEWAY_WS_URL`
- `OPENCLAW_GATEWAY_TOKEN`
- `OPENCLAW_GATEWAY_PASSWORD`
- `OPENCLAW_GATEWAY_TIMEOUT_SECONDS`
- `OPENCLAW_GATEWAY_DELIVER`
- `OPENCLAW_GATEWAY_MAX_CONCURRENCY`
- `GATEWAY_POOL_ENABLED`
- `GATEWAY_POOL_MAX_SIZE`
- `GATEWAY_POOL_ACQUIRE_TIMEOUT`
- `GATEWAY_POOL_IDLE_TIMEOUT`
- `TASK_CHAT_TIMEOUT_SECONDS`
- `TASK_SHORT_CHAT_TIMEOUT_SECONDS`
- `TASK_GATEWAY_FINAL_SILENCE_SECONDS`
- `TASK_GATEWAY_FIRST_TOKEN_TIMEOUT_SECONDS`
- `TASK_ASSUME_DONE_AFTER_TEXT_SILENCE`
- `TASK_JOB_TIMEOUT_SECONDS`
- `TASK_QUEUE_TIMEOUT_SECONDS`
- `TASK_STALE_RUNNING_MINUTES`
- `TASK_WATCHDOG_INTERVAL_SECONDS`
- `TASK_AGENT_CONCURRENCY`
- `TASK_GLOBAL_CHAT_CONCURRENCY`
- `TASK_PER_CONVERSATION_CONCURRENCY`
- `TASK_PER_AGENT_CONCURRENCY`
- `TASK_PER_USER_CONCURRENCY`
- `TASK_GLOBAL_JOB_CONCURRENCY`
- `MOCK_OPENCLAW`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
- `USER_UPLOAD_ROOT`
- `USER_OUTPUT_ROOT`
- `OPENCLAW_DAOBAN_WORKSPACE`
- `MAX_UPLOAD_MB`

## Chat Gateway

The browser only connects to:

```text
WS /api/ws/conversations/{conversation_id}?token={JWT}
```

`ws_chat.py` validates uploaded `file_ids`, resolves the Agent workspace, classifies the message as `short_chat`, `long_job`, or `pending_input`, creates a `task_runs` row, saves the user message with `run_id`, records `audit_logs.action=agent.invoke`, then hands execution to the in-process task executor. The executor selects a runner: short chat still streams through `OpenClawAdapter`, while implemented local jobs write `run_events`, update `phase/progress_message/duration_seconds`, and finish with one assistant summary for the same `run_id`. Task status events include `conversation_id` and `run_id`, and completed runs scan supported output roots for downloadable files.

WebSocket is only the realtime display channel. Final chat content and run status are recovered from `task_runs.output_text`, `task_runs.raw_payload`, and the assistant row in `messages`. If a page refreshes or the user switches Agents while a run is active, the frontend reloads `messages` and `ConversationDetail.active_run.output_text` to restore the visible assistant reply.

For short chat runs, if Gateway emits assistant text but does not send an explicit done event, the backend can mark the run `success` after `TASK_GATEWAY_FINAL_SILENCE_SECONDS` seconds of text silence when `TASK_ASSUME_DONE_AFTER_TEXT_SILENCE=true`.

If Gateway only emits connection health/tick frames and no assistant text, the backend marks the run `timeout` after `TASK_GATEWAY_FIRST_TOKEN_TIMEOUT_SECONDS` seconds. This prevents one silent Gateway call from occupying the Gateway concurrency slot for the full chat timeout.

Gateway `chat.send` requests keep the root `params` compatible with Gateway's strict schema: `sessionKey`, `message`, `deliver`, `timeoutMs`, `idempotencyKey`, and optional `attachments`. Web context such as Agent code, OpenClaw Agent id, run id, conversation id, client message id, and output directory is carried in the message context prefix instead of unsupported root params. `OPENCLAW_GATEWAY_DELIVER=true` is the default so the backend asks Gateway to actually deliver the message to the target Agent. `GATEWAY_POOL_ENABLED=true` reuses authenticated Gateway WebSocket connections without multiplexing; one pooled connection serves one active `stream_chat` call at a time. The default effective chat concurrency is 10, bounded by `GATEWAY_POOL_MAX_SIZE`, `TASK_GLOBAL_CHAT_CONCURRENCY`, and the non-pool fallback `OPENCLAW_GATEWAY_MAX_CONCURRENCY`.

For the knife-layout Agent (`image_daoban`, `image-daoban`, `daoban`, `workspace-image-daoban`, or `刀版合成`), uploaded PDFs are copied into `OPENCLAW_DAOBAN_WORKSPACE/data/input/userlook/run-{run_id}/` before the run is queued. `OPENCLAW_DAOBAN_WORKSPACE` must be writable by the backend and readable by OpenClaw Gateway; the Gateway request uses that `workspace_path` in both attachments and the message body.

Current v1 behavior supersedes the previous knife-layout Gateway flow: `image_daoban` jobs are handled by `DaobanJobRunner`, not Gateway `chat.send`. The runner copies PDFs into `OPENCLAW_DAOBAN_WORKSPACE/data/input/userlook/run-{run_id}/`, executes `scripts/run_daoban_job.py` locally, writes outputs under `DAOBAN_OUTPUT_ROOT`, and uses `TASK_PENDING_CONTEXT_TTL_HOURS` for PDF-only or prompt-only pending context.

To inspect the live Gateway protocol without exposing credentials, run the probe script. It reuses the normal Gateway handshake, redacts token/password/signature/private-key-like fields, saves the outbound request plus the first 50 inbound frames, and exits non-zero when no assistant output is received within the timeout:

```bash
python scripts/probe_openclaw_gateway.py --agent main --message "你是谁" --timeout 30
python scripts/probe_openclaw_gateway.py --agent image-daoban --message "你是谁" --timeout 30
python scripts/probe_openclaw_gateway.py --agent huizong-ceshi --message "你是谁" --timeout 30
```

The current chat queue follows the OpenClaw Feishu/Lark plugin scheduling model only as a reference: FastAPI keeps a process-level queue and applies layered limits by conversation, Agent, user, and global chat concurrency. `TASK_GLOBAL_CHAT_CONCURRENCY` is only a global concurrency guard; it is not a global serial queue.

Stop requests use an abort fast-path through the active dispatcher and then persist the final `cancelled` status. The current queue is still in a single FastAPI process. Production deployments must keep one backend worker process; multi-worker or multi-instance queue coordination requires a later Redis, Celery, or database-backed queue design.

The FastAPI lifespan watchdog scans old `running` and `queued` rows at startup and every `TASK_WATCHDOG_INTERVAL_SECONDS` seconds. Queued runs that exceed `TASK_QUEUE_TIMEOUT_SECONDS` become `timeout`; running runs that exceed `timeout_seconds` become `timeout`; running runs with stale heartbeat become `stale`. Watchdog updates do not overwrite terminal runs.

Gateway failure is returned to the browser as:

```text
OpenClaw Gateway 连接失败，请检查 openclaw-gateway.service 是否运行
```

## Files and Runs

- `POST /api/files/upload` accepts multipart field `upload`, enforces `MAX_UPLOAD_MB`, and supports common text/config, Office/OpenDocument, PDF, archive, and image files, including `txt`, `md`, `csv`, `json`, `yaml`, `docx`, `xlsx`, `pptx`, `pdf`, `zip`, `png`, `jpg`, `jpeg`, `gif`, `webp`, `bmp`, `tiff`, `svg`, `heic`, and `heif`.
- `GET /api/files` lists upload and output files visible to the current user.
- `GET /api/files/{file_id}/download` checks ownership and verifies the stored path stays inside the configured upload/output root.
- `GET /api/runs` lists TaskRun history.
- `GET /api/runs/{run_id}` returns TaskRun detail and registered output files.
- `POST /api/runs/{run_id}/cancel` requests cancellation.

`GET /api/runs` supports filters: `agent_id`, `conversation_id`, `status`, `run_type`, and `active_only=true`.

## Verification

```bash
.\.venv\Scripts\python.exe -m compileall app tests
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe -c "import app.main; print('ok')"
.\.venv\Scripts\python.exe -c "from app.core.security import hash_password, verify_password; h=hash_password('Admin@123456'); print(verify_password('Admin@123456', h))"
```
