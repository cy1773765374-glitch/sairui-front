# openclaw-userlook backend

Phase 04 adds Agent registry seeding, visible Agent list APIs, admin enable/disable controls, and Agent permission grants. WebSocket chat, OpenClaw invocation, file upload, and task execution are intentionally not implemented in this phase.

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

- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`

## Verification

```bash
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -c "import app.main; print('ok')"
.\.venv\Scripts\python.exe -c "from app.core.security import hash_password, verify_password; h=hash_password('Admin@123456'); print(verify_password('Admin@123456', h))"
```
