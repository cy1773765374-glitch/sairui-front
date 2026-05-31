# openclaw-userlook backend

Phase 02 adds MySQL configuration, SQLAlchemy ORM models, a table initialization script, and database health checks. Login, WebSocket, and Agent invocation are intentionally not implemented in this phase.

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
