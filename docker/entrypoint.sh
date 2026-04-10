#!/bin/sh
set -eu

CONFIG_PATH="${OPENMIURA_CONFIG:-configs/openmiura.yaml}"
HOST="${OPENMIURA_SERVER_HOST:-0.0.0.0}"
PORT="${OPENMIURA_SERVER_PORT:-8081}"
LOG_LEVEL="${OPENMIURA_LOG_LEVEL:-info}"
DB_PATH="${OPENMIURA_DB_PATH:-data/audit.db}"
SANDBOX_DIR="${OPENMIURA_SANDBOX_DIR:-data/sandbox}"

mkdir -p "$(dirname "$DB_PATH")" "$SANDBOX_DIR"

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

set -- openmiura run --config "$CONFIG_PATH" --host "$HOST" --port "$PORT" --log-level "$LOG_LEVEL"

case "${OPENMIURA_WITH_WORKERS:-false}" in
  1|true|TRUE|yes|YES|on|ON)
    set -- "$@" --with-workers
    ;;
esac

case "${OPENMIURA_RELOAD:-false}" in
  1|true|TRUE|yes|YES|on|ON)
    set -- "$@" --reload
    ;;
esac

exec "$@"
