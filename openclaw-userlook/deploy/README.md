# openclaw-userlook 生产部署说明

本目录提供面向 Ubuntu 服务器的生产部署脚本和配置模板。所有文件都是示例模板，需要人工审阅后再复制到系统目录；不要在未确认目标文件的情况下覆盖已有 Nginx 或 systemd 配置。

## 目录结构

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

示例配置默认项目部署路径为：

```bash
/opt/openclaw-userlook
```

如果实际路径不同，需要同步修改 Nginx 和 systemd 模板中的路径。

## 1. 创建 Python 虚拟环境

```bash
cd /opt/openclaw-userlook
bash deploy/scripts/install_backend.sh
```

该脚本会创建 `backend/.venv`、安装后端依赖、创建 `backend/logs`，并且只在 `backend/.env` 不存在时从 `backend/.env.example` 复制一份。

也可以手动执行：

```bash
cd /opt/openclaw-userlook/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p logs
```

## 2. 安装 requirements

如果没有使用 `install_backend.sh`，可以手动安装依赖：

```bash
cd /opt/openclaw-userlook/backend
.venv/bin/pip install -r requirements.txt
```

## 3. 配置 backend/.env

创建并编辑后端环境变量文件：

```bash
cd /opt/openclaw-userlook/backend
[ -f .env ] || cp .env.example .env
nano .env
```

生产环境重点检查：

- `APP_ENV=production`
- `DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/openclaw_userlook?charset=utf8mb4`
- `JWT_SECRET_KEY`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
- `OPENCLAW_GATEWAY_WS_URL=ws://127.0.0.1:18789`
- `OPENCLAW_GATEWAY_TOKEN`
- `OPENCLAW_GATEWAY_PASSWORD`
- `MOCK_OPENCLAW=false`
- `TASK_CHAT_TIMEOUT_SECONDS=120`
- `TASK_SHORT_CHAT_TIMEOUT_SECONDS=600`
- `TASK_GATEWAY_FINAL_SILENCE_SECONDS=20`
- `TASK_GATEWAY_FIRST_TOKEN_TIMEOUT_SECONDS=60`
- `TASK_ASSUME_DONE_AFTER_TEXT_SILENCE=true`
- `TASK_JOB_TIMEOUT_SECONDS=1800`
- `TASK_QUEUE_TIMEOUT_SECONDS=1800`
- `TASK_STALE_RUNNING_MINUTES=30`
- `TASK_WATCHDOG_INTERVAL_SECONDS=30`
- `TASK_GLOBAL_CHAT_CONCURRENCY=3`
- `USER_UPLOAD_ROOT=/data/openclaw-userlook/uploads`
- `USER_OUTPUT_ROOT=/data/openclaw-userlook/outputs`
- `OPENCLAW_DAOBAN_WORKSPACE=/home/cy/.openclaw/workspace-image-daoban`
- `MAX_UPLOAD_MB=100`
- 如启用企业微信 H5 登录，还需要配置 WeCom 相关变量。

密钥、Token、企业微信 Secret、OpenClaw Token 只应放在后端 `.env`，不要写入前端 `.env` 或提交到仓库。

## 4. 初始化数据库

先创建 MySQL 数据库：

```sql
CREATE DATABASE openclaw_userlook CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

再初始化表结构和基础数据：

```bash
cd /opt/openclaw-userlook/backend
.venv/bin/python -m app.init_db
```

从 Phase 10 升级到 Phase 11 的已有数据库，还需要执行幂等迁移脚本补齐任务生命周期字段和 `messages.run_id`：

```bash
cd /opt/openclaw-userlook/backend
.venv/bin/python -m app.migrations.phase11_task_run_lifecycle
```

## 5. 创建默认 admin

`app.init_db` 会根据 `.env` 中的以下配置确保默认管理员存在：

- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`

生产环境对外开放前必须修改默认密码。如只需要重新初始化预置 Agent，可以执行：

```bash
cd /opt/openclaw-userlook/backend
.venv/bin/python -m app.seed_agents
```

## 6. 构建前端

生产环境使用 `npm run build` 生成静态文件，并由 Nginx 托管 `frontend/dist`：

```bash
cd /opt/openclaw-userlook
bash deploy/scripts/build_frontend.sh
```

构建前先配置 `frontend/.env`。该值应填写 Nginx 对外提供服务的 HTTPS 域名：

```text
VITE_API_BASE_URL=https://your-domain.example
```

前端 WebSocket 地址也依赖该变量，因此需要保持为完整的 `http://` 或 `https://` origin。

## 7. 配置 Nginx

复制示例文件并手动编辑。`cp -n` 不会覆盖已存在的目标文件：

```bash
sudo cp -n /opt/openclaw-userlook/deploy/nginx/openclaw-userlook.conf.example /etc/nginx/sites-available/openclaw-userlook
sudo nano /etc/nginx/sites-available/openclaw-userlook
```

需要修改：

- `server_name`
- `ssl_certificate`
- `ssl_certificate_key`
- `root /opt/openclaw-userlook/frontend/dist`

模板已经包含：

- 监听 `443 ssl`。
- HTTP `80` 自动跳转 HTTPS。
- 从 `frontend/dist` 托管前端静态文件。
- `/api/` 反向代理到 `http://127.0.0.1:10009`。
- `/api/ws/` 支持 WebSocket proxy，包含 `Upgrade`、`Connection`、`proxy_http_version 1.1`。
- `client_max_body_size 100m` 上传大小限制。
- 不代理 OpenClaw Gateway。
- 不暴露 `18789`。

启用并检查 Nginx：

```bash
sudo ln -s /etc/nginx/sites-available/openclaw-userlook /etc/nginx/sites-enabled/openclaw-userlook
sudo nginx -t
sudo systemctl reload nginx
```

本阶段不实现自动申请证书。证书文件需要提前准备，并在 Nginx 配置中填写正确路径。

## 8. 启动 systemd

根据服务器实际情况创建服务用户和运行目录：

```bash
sudo useradd --system --home /opt/openclaw-userlook --shell /usr/sbin/nologin openclaw
sudo mkdir -p /data/openclaw-userlook/uploads /data/openclaw-userlook/outputs /opt/openclaw-userlook/backend/logs
sudo chown -R openclaw:openclaw /opt/openclaw-userlook /data/openclaw-userlook
```

复制并编辑后端服务模板。`cp -n` 不会覆盖已存在的目标文件：

```bash
sudo cp -n /opt/openclaw-userlook/deploy/systemd/openclaw-userlook-backend.service.example /etc/systemd/system/openclaw-userlook-backend.service
sudo nano /etc/systemd/system/openclaw-userlook-backend.service
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-userlook-backend.service
sudo systemctl status openclaw-userlook-backend.service
```

后端 systemd 服务要求：

- `WorkingDirectory` 指向 `backend`。
- `EnvironmentFile` 指向 `backend/.env`。
- `ExecStart` 使用 `backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 10009`。
- `Restart=always`。
- 日志写入 `backend/logs/`。

当前任务队列仿照 OpenClaw 官方 Feishu/Lark 插件的调度思路：同一 `conversation_id` 串行，不同 conversation / 不同 Agent 可以并发，停止请求通过 active dispatcher 走 abort fast-path。该实现仍是单 FastAPI 进程内队列，生产环境必须保持后端服务为单个 worker 进程；多 worker / 多实例需要后续改为 Redis、Celery 或数据库队列。

`openclaw-userlook-worker.service.example` 只是占位模板。本阶段仍不启用 Redis、Celery 或独立 worker，任务执行、conversation 进程内队列和 watchdog 由 FastAPI lifespan 内置后台任务承载。除非替换为真实命令，否则不要启用该服务。

## 9. 检查 OpenClaw Gateway 是否运行

OpenClaw Gateway 需要作为独立服务运行，并且只监听本机地址：

```bash
sudo systemctl status openclaw-gateway.service
ss -lntp | grep 18789
```

期望监听地址：

```text
127.0.0.1:18789
```

不要通过 Nginx 或防火墙暴露 `18789`。

## 10. 检查 WebSocket 代理是否正常

先检查后端和 Nginx API 代理：

```bash
cd /opt/openclaw-userlook
bash deploy/scripts/check_service.sh
PUBLIC_URL=https://your-domain.example bash deploy/scripts/check_service.sh
```

真实 WebSocket 检查需要有效 JWT 和会话 ID。可以先在页面中创建或选择一个 conversation，再执行：

```bash
wscat -c 'wss://your-domain.example/api/ws/conversations/<conversation_id>?token=<JWT>'
```

浏览器只应连接 HTTPS 域名下的 `/api/ws/...`，不能直接连接 `127.0.0.1:18789`，也不能连接任何公网 `18789` 端口。

## 手动启动后端

不通过 systemd 排查问题时，可以临时手动启动：

```bash
cd /opt/openclaw-userlook
bash deploy/scripts/start_backend.sh
```

该脚本会启动 uvicorn，监听 `127.0.0.1:10009`，并把日志写入 `backend/logs/`。

## 验收检查

- `deploy/` 包含 Nginx、systemd、scripts 和本 README。
- 执行 `npm run build` 后存在 `frontend/dist`。
- FastAPI 监听 `127.0.0.1:10009`。
- Nginx 提供 HTTPS，并代理 `/api/`。
- `/api/ws/` 可以升级 WebSocket 连接。
- OpenClaw Gateway 保持本机监听 `127.0.0.1:18789`。
- 本阶段不要求 Docker、Kubernetes、自动证书申请、Redis 或 Celery。
