#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Bright Future Grant — one-command server bootstrap.
#
# Run this on a FRESH Ubuntu/Debian VPS (root or sudo). It will:
#   1. Install Docker + the compose plugin (if missing).
#   2. Clone the repository.
#   3. Create .env with a strong SECRET_KEY (and any values you pass in).
#   4. Build and start the app + Cloudflare Tunnel via docker compose.
#
# Usage:
#   CLOUDFLARE_TUNNEL_TOKEN=xxxx ADMIN_EMAIL=you@brightfuturegrant.com \
#   ADMIN_PASSWORD='S0me-Str0ng-Pass' bash scripts/deploy_server.sh
#
# Everything is overridable with environment variables.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/zhavihubb/brightpath-foundation.git}"
APP_DIR="${APP_DIR:-$HOME/brightpath-foundation}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@brightfuturegrant.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
SMTP_HOST="${SMTP_HOST:-}"
SMTP_PORT="${SMTP_PORT:-587}"
SMTP_USER="${SMTP_USER:-}"
SMTP_PASS="${SMTP_PASS:-}"
SMTP_FROM="${SMTP_FROM:-no-reply@brightfuturegrant.com}"
CLOUDFLARE_TUNNEL_TOKEN="${CLOUDFLARE_TUNNEL_TOKEN:-}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

# --- 1. Docker -------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker\u2026"
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" || true
else
  say "Docker already installed ($(docker --version))"
fi

# --- 2. Clone --------------------------------------------------------------
if [ -d "$APP_DIR/.git" ]; then
  say "Updating existing checkout in $APP_DIR"
  git -C "$APP_DIR" pull --ff-only
else
  say "Cloning $REPO_URL"
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# --- 3. .env ---------------------------------------------------------------
if [ ! -f .env ]; then
  say "Creating .env with a fresh SECRET_KEY"
  SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null \
    || head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 48)"
  if [ -z "$ADMIN_PASSWORD" ]; then
    ADMIN_PASSWORD="$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 16)"
    echo "    Generated admin password: $ADMIN_PASSWORD"
  fi
  cat > .env <<EOF
SECRET_KEY=$SECRET_KEY
PORT=8080
BRIGHTPATH_DATA_DIR=/data
ADMIN_EMAIL=$ADMIN_EMAIL
ADMIN_PASSWORD=$ADMIN_PASSWORD
SMTP_HOST=$SMTP_HOST
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASS=$SMTP_PASS
SMTP_FROM=$SMTP_FROM
CLOUDFLARE_TUNNEL_TOKEN=$CLOUDFLARE_TUNNEL_TOKEN
EOF
  chmod 600 .env
  echo "    Wrote $APP_DIR/.env (keep it secret)"
else
  say ".env already exists \u2014 leaving it untouched"
fi

# --- 4. Run ----------------------------------------------------------------
say "Building and starting the stack"
if docker compose version >/dev/null 2>&1; then
  docker compose up -d --build
else
  docker-compose up -d --build
fi

say "Status"
docker compose ps || docker-compose ps

cat <<'EOF'

----------------------------------------------------------------------------
Done. The app is now running and the Cloudflare Tunnel is connected.

  * If you have not yet created the tunnel, run (on your laptop):
        CF_API_TOKEN=xxxx python3 scripts/cloudflare_setup.py
    then paste the printed CLOUDFLARE_TUNNEL_TOKEN into .env and re-run this
    script (or `docker compose up -d`).

  * Set the nameservers Cloudflare gave you at WhoGoHost, wait for the zone to
    go "Active", then open https://app.brightfuturegrant.com
----------------------------------------------------------------------------
EOF
