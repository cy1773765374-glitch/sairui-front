当前项目名称：openclaw-userlook

项目目标：
构建一个企业内部 OpenClaw 多 Agent Web 门户。用户可以通过网页或企业微信 H5 页面进入系统，选择不同 OpenClaw Agent 进行对话、提交任务、上传文件、查看任务进度、下载输出结果。系统后端不直接暴露 OpenClaw Gateway 给浏览器，而是由 FastAPI 作为统一接入层，通过 WebSocket 连接本机 OpenClaw Gateway，再把结果转发给前端。

技术栈：
前端：
- Vue3
- Vite
- TypeScript
- Element Plus
- Pinia
- Vue Router
- axios
- 原生 WebSocket

后端：
- Python 3.12
- FastAPI
- SQLAlchemy 2.x
- MySQL 8.0
- Pydantic
- WebSocket
- asyncio
- python-jose
- passlib

Agent 调用：
- 主路径：FastAPI 后端通过 WebSocket 连接 OpenClaw Gateway
- OpenClaw Gateway 默认地址：ws://127.0.0.1:18789
- 不允许浏览器直接连接 OpenClaw Gateway
- CLI 只作为 fallback 或调试工具，不作为主流程

部署：
- Nginx HTTPS
- systemd
- MySQL
- 前端静态构建
- 后端 uvicorn 服务
- OpenClaw gateway.service 独立运行

端口规划：
- 后端 FastAPI：127.0.0.1:10009
- 前端开发服务：127.0.0.1:10010
- OpenClaw Gateway：127.0.0.1:18789
- 对外只暴露 Nginx 443

安全原则：
1. 浏览器只访问 FastAPI，不直接访问 OpenClaw Gateway。
2. OpenClaw Gateway 只监听本机地址，不暴露公网。
3. 后端统一处理登录、权限、Agent 可见性、审计日志、任务记录。
4. 文件上传和输出文件按用户隔离。
5. 高风险 Agent 需要在配置中标记。
6. 所有用户调用 Agent 的行为都必须入库记录。
7. 所有密钥、token、企微 secret、OpenClaw token 只能放在后端 .env，不能进入前端。

开发要求：
- 每个阶段只完成当前阶段目标，不要跨阶段开发。
- 不要一次性实现所有功能。
- 每阶段完成后保证项目可启动、可测试。
- 每阶段更新 README 或对应说明。
- 每阶段保证 .gitignore 合理，不提交 .env、node_modules、venv、上传文件、输出文件、日志文件。
- 每阶段完成后给出检查命令。