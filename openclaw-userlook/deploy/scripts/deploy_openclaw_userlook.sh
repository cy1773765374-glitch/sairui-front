#!/usr/bin/env bash
set -euo pipefail

export http_proxy="${http_proxy:-http://127.0.0.1:17897}"
export https_proxy="${https_proxy:-http://127.0.0.1:17897}"
export HTTP_PROXY="${HTTP_PROXY:-$http_proxy}"
export HTTPS_PROXY="${HTTPS_PROXY:-$https_proxy}"

REPO_DIR="${REPO_DIR:-/opt/sairui-front}"
PROJECT_SUBDIR="${PROJECT_SUBDIR:-openclaw-userlook}"
APP_DIR="${APP_DIR:-/opt/openclaw-userlook}"
BRANCH="${BRANCH:-main}"

cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

SOURCE_DIR="$REPO_DIR/$PROJECT_SUBDIR"
if [ ! -d "$SOURCE_DIR/backend" ] || [ ! -d "$SOURCE_DIR/frontend" ]; then
  echo "source project not found: $SOURCE_DIR" >&2
  exit 1
fi

SOURCE_REAL="$(realpath "$SOURCE_DIR")"
APP_REAL="$(realpath -m "$APP_DIR")"

if [ "$SOURCE_REAL" != "$APP_REAL" ]; then
  mkdir -p "$APP_DIR"
  rsync -a --delete \
    --exclude 'backend/.venv/' \
    --exclude 'backend/.env' \
    --exclude 'backend/storage/' \
    --exclude 'frontend/node_modules/' \
    --exclude 'frontend/.env' \
    --exclude 'frontend/.env.local' \
    --exclude 'frontend/dist/' \
    "$SOURCE_DIR/" "$APP_DIR/"
fi

if [ ! -x "$APP_DIR/backend/.venv/bin/pip" ]; then
  bash "$APP_DIR/deploy/scripts/install_backend.sh"
fi

cd "$APP_DIR/backend"
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.migrations.run_all

cd "$APP_DIR/frontend"
npm ci

cd "$APP_DIR"
bash deploy/scripts/build_frontend.sh

sudo systemctl restart openclaw-userlook-backend.service
sudo systemctl reload nginx
