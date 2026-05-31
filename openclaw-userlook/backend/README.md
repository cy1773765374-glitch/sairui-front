# openclaw-userlook backend

Phase 06 keeps the browser-facing FastAPI WebSocket chat API from Phase 05 and adds a backend-only OpenClaw Gateway adapter. `MOCK_OPENCLAW=true` keeps the Phase 05 mock stream available; `MOCK_OPENCLAW=false` sends chat requests from FastAPI to OpenClaw Gateway over WebSocket.

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
- `OPENCLAW_GATEWAY_TIMEOUT_SECONDS`
- `MOCK_OPENCLAW`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`

## Chat Gateway

The browser only connects to:

```text
WS /api/ws/conversations/{conversation_id}?token={JWT}
```

`ws_chat.py` saves the user message, records `audit_logs.action=agent.invoke`, then calls `OpenClawAdapter`. The adapter either streams the mock reply or delegates to `OpenClawGatewayClient`, which owns the Gateway URL, token header, request payload, and response parsing.

Gateway failure is returned to the browser as:

```text
OpenClaw Gateway 连接失败，请检查 openclaw-gateway.service 是否运行
```

## Verification

```bash
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -c "import app.main; print('ok')"
.\.venv\Scripts\python.exe -c "from app.core.security import hash_password, verify_password; h=hash_password('Admin@123456'); print(verify_password('Admin@123456', h))"
```
