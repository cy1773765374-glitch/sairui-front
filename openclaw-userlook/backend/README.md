# openclaw-userlook backend

Phase 01 only provides the FastAPI project skeleton and a health check endpoint. Login, database, WebSocket, and Agent invocation are intentionally not implemented in this phase.

## Requirements

- Python 3.12

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
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
