# openclaw-userlook

`openclaw-userlook` is an OpenClaw multi-Agent enterprise workspace.

Phase 02 adds MySQL configuration, SQLAlchemy ORM models, a table initialization script, and database health checks. Login, WebSocket, and Agent invocation are intentionally not implemented yet.

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

Set `DATABASE_URL` in `backend/.env`, then create tables:

```bash
python -m app.init_db
```

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

## Frontend Setup

```bash
cd frontend
npm install
copy .env.example .env
npm run dev -- --host 127.0.0.1 --port 10010
```

Open `http://127.0.0.1:10010` and confirm the dashboard displays the backend health check result.

## Environment

Backend `.env` values:

- `APP_NAME`
- `APP_ENV`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `OPENCLAW_GATEWAY_WS_URL`
- `DATABASE_URL`

Frontend `.env` values:

- `VITE_API_BASE_URL`

Default API base URL:

```text
http://127.0.0.1:10009
```
