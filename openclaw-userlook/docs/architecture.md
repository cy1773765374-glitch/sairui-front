# Architecture

## Phase 01 Scope

This phase creates the `openclaw-userlook` project skeleton only.

Implemented:

- FastAPI backend application entrypoint.
- `/api/health` health check route.
- Environment-based backend settings.
- Vue 3, Vite, TypeScript frontend skeleton.
- Element Plus, Pinia, Vue Router, and axios wiring.
- Dashboard page that displays the system name, phase, and backend health result.

Not implemented in Phase 01:

- Login and permissions.
- Database models or migrations.
- WebSocket connection to OpenClaw Gateway.
- Agent invocation.
- File upload or output management.

## Runtime Topology

The browser talks to the FastAPI backend only. Later phases may let the backend connect to the local OpenClaw Gateway, but the browser must not connect to the gateway directly.

```text
Browser -> FastAPI backend -> OpenClaw Gateway
```

## Ports

| Component | Address |
| --- | --- |
| FastAPI backend | `127.0.0.1:10009` |
| Vite frontend dev server | `127.0.0.1:10010` |
| OpenClaw Gateway | `127.0.0.1:18789` |

Only the backend and frontend development ports are used in Phase 01.
