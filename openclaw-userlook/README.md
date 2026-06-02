# openclaw-userlook

`openclaw-userlook` is an OpenClaw multi-Agent enterprise workspace.

Phase 10 builds on the Phase 09 WeCom H5 foundation and adds production deployment templates under `deploy/` for Ubuntu, Nginx HTTPS, systemd, backend installation, frontend build, backend startup, and service checks. The browser still connects only to FastAPI; FastAPI calls OpenClaw Gateway at `OPENCLAW_GATEWAY_WS_URL` and forwards `assistant_delta`, `assistant_done`, `run_status`, and `error` events. Redis, Celery, Feishu OAuth, WeCom JS-SDK, directory sync, message push, Docker, Kubernetes, automatic certificate issuance, and browser-to-Gateway direct access are intentionally not implemented.

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
- python-multipart

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
- `USER_UPLOAD_ROOT`
- `USER_OUTPUT_ROOT`
- `MAX_UPLOAD_MB`

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

- `POST /api/auth/register` creates a `pending` normal user that requires admin approval before login.
- `POST /api/auth/login` returns a JWT only for `active` users.
- `GET /api/auth/me` returns the current JWT user.
- `GET /api/wecom/login-url` returns a WeCom OAuth URL. With `WECOM_MOCK_LOGIN=true`, it returns a mock callback URL.
- `GET /api/wecom/callback?code=...&state=...` resolves the WeCom identity, writes `identity_bindings(provider=wecom)`, and returns a JWT for active users. New WeCom users default to `WECOM_DEFAULT_USER_STATUS`, which is `pending` in the example config.
- `GET /api/wecom/me` returns the current user's WeCom binding information.
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

Conversation endpoints:

- `POST /api/conversations` creates a conversation for an authorized Agent and generates a `web:{user_id}:{agent_code}:{conversation_id}` session key.
- `GET /api/conversations` lists the current user's conversations.
- `GET /api/conversations/{conversation_id}` returns conversation detail and message history. Users can only read their own conversations; admins can read all conversations.

Chat WebSocket:

- `WS /api/ws/conversations/{conversation_id}?token={JWT}` connects the browser to FastAPI.
- Browser messages use `{"type":"user_message","content":"你好","file_ids":[]}`.
- With `MOCK_OPENCLAW=true`, FastAPI returns the Phase 05 mock streaming reply.
- With `MOCK_OPENCLAW=false`, FastAPI calls OpenClaw Gateway through `OpenClawAdapter` and `OpenClawGatewayClient`.
- Gateway address, token, and protocol details stay in the backend and are never returned to the browser.
- Gateway completion events such as `done`, `assistant_done`, or `success` may carry final text in `content`, `answer`, `message`, or nested `data`; FastAPI forwards that text to the browser before saving the assistant message.
- Each user Agent call records an `audit_logs` row with `action=agent.invoke`.
- If Gateway cannot be reached, the browser receives: `OpenClaw Gateway 连接失败，请检查 openclaw-gateway.service 是否运行`.

Preset Agents can also be initialized independently:

```bash
python -m app.seed_agents
```

Phase 07 files and runs:

- `POST /api/files/upload` accepts multipart field `upload`, stores files under `USER_UPLOAD_ROOT/{user_id}/{yyyyMMdd}`, enforces `MAX_UPLOAD_MB`, and records `purpose=upload`.
- `GET /api/files` lists upload and output files visible to the current user. Admin users can list all files.
- `GET /api/files/{file_id}/download` checks ownership and verifies the stored path stays inside the configured upload/output root before serving.
- `GET /api/runs` lists TaskRun history.
- `GET /api/runs/{run_id}` returns TaskRun detail and registered output files.
- Chat WebSocket messages can carry uploaded `file_ids`. Each message creates a `task_runs` row, pushes `run_status` with `run_id`, and scans `USER_OUTPUT_ROOT/{user_id}/{yyyyMMdd}/run_{run_id}` for output files after completion.

Phase 08 frontend workspace:

- Dashboard shows backend health, current user, available Agent count, recent TaskRun records, and recent conversations.
- Normal-user Agent marketplace shows authorized Agent names only; clicking an Agent name card opens chat.
- Admin users can still inspect Agent details and access Agent management.
- Chat workspace uses a three-column layout: available Agents and conversation history on the left, streaming chat and file upload in the center, and Agent/task/output details on the right.
- High-risk Agents require a confirmation dialog before first entering chat in the current page session.
- WebSocket disconnects show Element Plus notifications and retry the conversation channel up to three times.
- Task center and file center use Element Plus tables for status, timestamps, output files, file metadata, and authenticated downloads.
- Admin users see the admin entry page, user management, and Agent management menus; normal users do not.

Phase 09 WeCom H5 foundation:

- `src/utils/env.ts` detects the WeCom WebView by user agent.
- WeCom backend endpoints are retained as a foundation, but the frontend login page does not expose WeCom login yet.
- Visiting protected pages without a token routes to `/login` for web username/password login.
- `/wecom/callback` exchanges `code` and `state` through FastAPI and stores the returned system JWT. The frontend never reads or stores `WECOM_SECRET`.
- Dashboard shows the current login source; web login uses `password`.

Phase 10 production deployment templates:

- `deploy/nginx/openclaw-userlook.conf.example` provides an HTTPS Nginx template, HTTP-to-HTTPS redirect, frontend `dist` static hosting, `/api/` backend proxy, and `/api/ws/` WebSocket proxy.
- `deploy/systemd/openclaw-userlook-backend.service.example` runs uvicorn from `backend/.venv` on `127.0.0.1:10009` and writes logs under `backend/logs/`.
- `deploy/scripts/` includes backend install, frontend build, manual backend start, and service check scripts.
- `deploy/README.md` documents manual Ubuntu deployment steps without overwriting system files or exposing OpenClaw Gateway port `18789`.

## Frontend Setup

```bash
cd frontend
npm install
copy .env.example .env
npm run dev -- --host 127.0.0.1 --port 10010
```

Open `http://127.0.0.1:10010`, register a normal user, approve that user from the admin user page, grant Agent permissions from the admin Agent management page if needed, then confirm the approved user only sees authorized enabled Agent name cards and no admin menu. Click an Agent name card to enter the chat workspace, upload a supported file before sending if needed, and verify streaming replies. The Dashboard links into recent conversations, Task Center, and File Center.

## Environment

Backend `.env` values:

- `APP_NAME`
- `APP_ENV`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `OPENCLAW_GATEWAY_WS_URL`
- `OPENCLAW_GATEWAY_TOKEN`
- `OPENCLAW_GATEWAY_PASSWORD`
- `OPENCLAW_GATEWAY_TIMEOUT_SECONDS`
- `MOCK_OPENCLAW`
- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
- `WECOM_CORP_ID`
- `WECOM_AGENT_ID`
- `WECOM_SECRET`
- `WECOM_REDIRECT_URI`
- `WECOM_MOCK_LOGIN`
- `WECOM_DEFAULT_USER_STATUS`

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
