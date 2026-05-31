# openclaw-userlook Production Deployment

This directory contains production deployment templates for an Ubuntu server. The files are examples only. Review and copy them into system locations manually; do not run commands that overwrite existing Nginx or systemd files without checking the target first.

## Layout

```text
deploy/
├── nginx/
│   └── openclaw-userlook.conf.example
├── systemd/
│   ├── openclaw-userlook-backend.service.example
│   └── openclaw-userlook-worker.service.example
├── scripts/
│   ├── install_backend.sh
│   ├── build_frontend.sh
│   ├── start_backend.sh
│   └── check_service.sh
└── README.md
```

Assumed production project path in the examples:

```bash
/opt/openclaw-userlook
```

If you deploy elsewhere, update all paths in the Nginx and systemd templates.

## 1. Create Python Virtual Environment

```bash
cd /opt/openclaw-userlook
bash deploy/scripts/install_backend.sh
```

The script creates `backend/.venv`, installs dependencies, creates `backend/logs`, and copies `backend/.env.example` to `backend/.env` only when `.env` does not exist.

Manual equivalent:

```bash
cd /opt/openclaw-userlook/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p logs
```

## 2. Install Requirements

If you did not use `install_backend.sh`, install requirements manually:

```bash
cd /opt/openclaw-userlook/backend
.venv/bin/pip install -r requirements.txt
```

## 3. Configure backend/.env

Create and edit the backend environment file:

```bash
cd /opt/openclaw-userlook/backend
[ -f .env ] || cp .env.example .env
nano .env
```

Production values to review:

- `APP_ENV=production`
- `DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/openclaw_userlook?charset=utf8mb4`
- `JWT_SECRET_KEY`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
- `OPENCLAW_GATEWAY_WS_URL=ws://127.0.0.1:18789`
- `OPENCLAW_GATEWAY_TOKEN`
- `MOCK_OPENCLAW=false`
- `USER_UPLOAD_ROOT=/data/openclaw-userlook/uploads`
- `USER_OUTPUT_ROOT=/data/openclaw-userlook/outputs`
- `MAX_UPLOAD_MB=100`
- WeCom settings when H5 login is enabled.

Do not put secrets in frontend `.env` or committed files.

## 4. Initialize Database

Create the MySQL database first:

```sql
CREATE DATABASE openclaw_userlook CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Then initialize tables:

```bash
cd /opt/openclaw-userlook/backend
.venv/bin/python -m app.init_db
```

## 5. Create Default Admin

`app.init_db` also ensures the default admin from these `.env` values:

- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`

Change the default password before production exposure. If you need to re-seed Agents only:

```bash
cd /opt/openclaw-userlook/backend
.venv/bin/python -m app.seed_agents
```

## 6. Build Frontend

For production, build static assets and let Nginx serve `frontend/dist`:

```bash
cd /opt/openclaw-userlook
bash deploy/scripts/build_frontend.sh
```

Set `frontend/.env` before building. Use the public HTTPS origin that Nginx serves:

```text
VITE_API_BASE_URL=https://your-domain.example
```

The frontend WebSocket helper also uses this value, so keep it as an absolute `http://` or `https://` origin.

## 7. Configure Nginx

Copy and edit the example:

```bash
sudo cp -n /opt/openclaw-userlook/deploy/nginx/openclaw-userlook.conf.example /etc/nginx/sites-available/openclaw-userlook
sudo nano /etc/nginx/sites-available/openclaw-userlook
```

Update:

- `server_name`
- `ssl_certificate`
- `ssl_certificate_key`
- `root /opt/openclaw-userlook/frontend/dist`

The template:

- Listens on `443 ssl`.
- Redirects HTTP `80` to HTTPS.
- Serves frontend static files from `frontend/dist`.
- Proxies `/api/` to `http://127.0.0.1:10009`.
- Proxies `/api/ws/` with WebSocket headers: `Upgrade`, `Connection`, and `proxy_http_version 1.1`.
- Sets `client_max_body_size 100m`.
- Does not proxy OpenClaw Gateway and does not expose port `18789`.

Enable and test:

```bash
sudo ln -s /etc/nginx/sites-available/openclaw-userlook /etc/nginx/sites-enabled/openclaw-userlook
sudo nginx -t
sudo systemctl reload nginx
```

Certificate issuance is intentionally not automated in this phase.

## 8. Start systemd

Create a service user and writable runtime directories as appropriate for your server:

```bash
sudo useradd --system --home /opt/openclaw-userlook --shell /usr/sbin/nologin openclaw
sudo mkdir -p /data/openclaw-userlook/uploads /data/openclaw-userlook/outputs /opt/openclaw-userlook/backend/logs
sudo chown -R openclaw:openclaw /opt/openclaw-userlook /data/openclaw-userlook
```

Copy and edit the backend service:

```bash
sudo cp -n /opt/openclaw-userlook/deploy/systemd/openclaw-userlook-backend.service.example /etc/systemd/system/openclaw-userlook-backend.service
sudo nano /etc/systemd/system/openclaw-userlook-backend.service
```

Then start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-userlook-backend.service
sudo systemctl status openclaw-userlook-backend.service
```

The worker service is a placeholder template because Phase 10 does not implement Redis, Celery, or another standalone worker. Do not enable it unless you replace `ExecStart` with a real command.

## 9. Check OpenClaw Gateway

OpenClaw Gateway must run independently on the server and listen locally:

```bash
sudo systemctl status openclaw-gateway.service
ss -lntp | grep 18789
```

Expected binding:

```text
127.0.0.1:18789
```

Do not expose `18789` through Nginx or the firewall.

## 10. Check WebSocket Proxy

Run basic backend and proxy checks:

```bash
cd /opt/openclaw-userlook
bash deploy/scripts/check_service.sh
PUBLIC_URL=https://your-domain.example bash deploy/scripts/check_service.sh
```

For a real WebSocket check, create or choose a conversation in the UI, get a valid JWT, then test:

```bash
wscat -c 'wss://your-domain.example/api/ws/conversations/<conversation_id>?token=<JWT>'
```

The browser should connect only to `/api/ws/...` on the HTTPS domain. It must never connect directly to `127.0.0.1:18789` or a public `18789` port.

## Manual Backend Start

For one-off troubleshooting without systemd:

```bash
cd /opt/openclaw-userlook
bash deploy/scripts/start_backend.sh
```

This starts uvicorn on `127.0.0.1:10009` and writes logs to `backend/logs/`.

## Verification Checklist

- `deploy/` contains Nginx, systemd, scripts, and this README.
- `frontend/dist` exists after `npm run build`.
- FastAPI listens on `127.0.0.1:10009`.
- Nginx serves HTTPS and proxies `/api/`.
- `/api/ws/` upgrades WebSocket connections.
- OpenClaw Gateway remains local-only on `127.0.0.1:18789`.
- No Docker, Kubernetes, certificate automation, Redis, or Celery is required for this phase.
