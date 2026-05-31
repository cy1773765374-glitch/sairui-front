# openclaw-userlook

`openclaw-userlook` is an OpenClaw multi-Agent enterprise workspace.

Phase 04 adds the Agent registry, visible Agent list, Agent enable/disable controls, and Agent permission grants. WebSocket chat, OpenClaw invocation, file upload, task execution, and WeCom login are intentionally not implemented yet.

## Stack

Frontend:

- Vue 3
- Vite
- TypeScript
- Element Plus
- Pinia
- Vue Router
- axios

Backend:

- Python 3.12
- FastAPI
- Pydantic
- uvicorn
- SQLAlchemy 2.x
- PyMySQL
- MySQL 8.0
- python-jose
- passlib

## Ports

| Component | Address |
| --- | --- |
| Backend FastAPI | `127.0.0.1:10009` |
| Frontend Vite dev server | `127.0.0.1:10010` |
| OpenClaw Gateway | `127.0.0.1:18789` |

## Backend Setup

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 10009
```

Create the MySQL database before initializing tables:

```sql
CREATE DATABASE openclaw_userlook CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Set `DATABASE_URL` and JWT/admin values in `backend/.env`, then create tables and ensure the default admin and preset Agents exist:

```bash
python -m app.init_db
```

Default admin values come from:

- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`

Health check:

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

Authentication endpoints:

- `POST /api/auth/register` creates a `pending` user.
- `POST /api/auth/login` returns a JWT only for `active` users.
- `GET /api/auth/me` returns the current JWT user.
- `GET /api/admin/users` lists users for admins.
- `POST /api/admin/users/{user_id}/approve` activates a user.
- `POST /api/admin/users/{user_id}/disable` disables a user.

Agent endpoints:

- `GET /api/agents` lists enabled Agents visible to the current user.
- `GET /api/agents/{agent_id}` returns one visible Agent by Agent code.
- `GET /api/admin/agents` lists all Agents for admins, including disabled Agents.
- `POST /api/admin/agents/{agent_id}/enable` enables an Agent.
- `POST /api/admin/agents/{agent_id}/disable` disables an Agent.
- `POST /api/admin/agents/{agent_id}/permissions` grants an Agent to one `user_id` or one `role`.

Preset Agents can also be initialized independently:

```bash
python -m app.seed_agents
```

## Frontend Setup

```bash
cd frontend
npm install
copy .env.example .env
npm run dev -- --host 127.0.0.1 --port 10010
```

Open `http://127.0.0.1:10010`, log in with the default admin, register a normal user, approve that user from the admin user page, grant Agent permissions from the Agent management page, then confirm the approved user only sees authorized Agents.

## Environment

Backend `.env` values:

- `APP_NAME`
- `APP_ENV`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `OPENCLAW_GATEWAY_WS_URL`
- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`

Frontend `.env` values:

- `VITE_API_BASE_URL`

Default API base URL:

```text
http://127.0.0.1:10009
```

## Verification

```bash
cd backend
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -c "import app.main; print('ok')"
.\.venv\Scripts\python.exe -c "from app.core.security import hash_password, verify_password; h=hash_password('Admin@123456'); print(verify_password('Admin@123456', h))"

cd ..\frontend
npm.cmd run build
```
