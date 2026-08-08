#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
RELOAD="${RELOAD:-1}"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"
BUILD_CSS="${BUILD_CSS:-1}"
START_POSTGRES="${START_POSTGRES:-1}"
DB_NAME="${DB_NAME:-blog}"

PG_BIN=""
for candidate in \
  /opt/homebrew/opt/postgresql@16/bin \
  /opt/homebrew/opt/postgresql@17/bin \
  /opt/homebrew/opt/postgresql@15/bin \
  /usr/local/opt/postgresql@16/bin \
  /opt/homebrew/bin \
  /usr/local/bin
do
  if [[ -x "$candidate/pg_isready" ]]; then
    PG_BIN="$candidate"
    break
  fi
done

cleanup() {
  if [[ -n "${CSS_WATCH_PID:-}" ]] && kill -0 "$CSS_WATCH_PID" 2>/dev/null; then
    kill "$CSS_WATCH_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "==> Techfrontier blog"

if [[ ! -f .env ]]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
fi

if [[ ! -d .venv ]]; then
  echo "==> Creating virtualenv"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import fastapi" >/dev/null 2>&1; then
  echo "==> Installing Python dependencies"
  pip install -r requirements.txt
fi

if [[ "$BUILD_CSS" == "1" ]]; then
  if [[ ! -d node_modules ]]; then
    echo "==> Installing npm dependencies"
    npm install
  fi
  echo "==> Building Tailwind CSS"
  npm run build:css
fi

ensure_postgres() {
  if [[ -z "$PG_BIN" ]]; then
    echo "!! PostgreSQL client tools not found."
    echo "   Install with: brew install postgresql@16 && brew services start postgresql@16"
    return 1
  fi

  export PATH="$PG_BIN:$PATH"

  if ! pg_isready -q; then
    if [[ "$START_POSTGRES" != "1" ]]; then
      echo "!! PostgreSQL is not running on port 5432."
      return 1
    fi
    echo "==> Starting PostgreSQL"
    if command -v brew >/dev/null 2>&1; then
      brew services start postgresql@16 >/dev/null 2>&1 \
        || brew services start postgresql@17 >/dev/null 2>&1 \
        || brew services start postgresql@15 >/dev/null 2>&1 \
        || brew services start postgresql >/dev/null 2>&1 \
        || true
    fi
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      if pg_isready -q; then
        break
      fi
      sleep 0.5
    done
  fi

  if ! pg_isready -q; then
    echo "!! Could not connect to PostgreSQL on port 5432."
    echo "   Start it with: brew services start postgresql@16"
    return 1
  fi

  # Ensure role + database exist for the default .env credentials.
  createuser -s postgres >/dev/null 2>&1 || true
  psql -d postgres -v ON_ERROR_STOP=1 -c "ALTER USER postgres WITH PASSWORD 'postgres';" >/dev/null 2>&1 || true
  if ! psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
    echo "==> Creating database '${DB_NAME}'"
    createdb -O postgres "$DB_NAME" >/dev/null 2>&1 || createdb "$DB_NAME"
  fi
}

if [[ "$RUN_MIGRATIONS" == "1" ]]; then
  ensure_postgres
  echo "==> Running database migrations"
  if ! alembic upgrade head; then
    echo "!! Migration failed. Check DATABASE_URL in .env."
    exit 1
  fi
fi

if [[ "$RELOAD" == "1" && "$BUILD_CSS" == "1" ]]; then
  echo "==> Watching Tailwind CSS"
  npm run watch:css >/tmp/techfrontier-tailwind.log 2>&1 &
  CSS_WATCH_PID=$!
fi

UVICORN_ARGS=(app.main:app --host "$HOST" --port "$PORT")
if [[ "$RELOAD" == "1" ]]; then
  UVICORN_ARGS+=(--reload)
fi

echo "==> Starting server at http://${HOST}:${PORT}"
echo "    Admin:    http://${HOST}:${PORT}/admin"
echo "    API docs: http://${HOST}:${PORT}/docs"
exec uvicorn "${UVICORN_ARGS[@]}"
