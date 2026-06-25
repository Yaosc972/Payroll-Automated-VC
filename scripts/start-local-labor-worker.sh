#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${SIGMA_WORKER_ENV_FILE:-$ROOT_DIR/.env.worker.local}"
WORKER_ID="${SIGMA_WORKER_ID:-local-overseas-labor-1}"
INTERVAL="${SIGMA_WORKER_INTERVAL:-5}"

if [[ ! -f "$ENV_FILE" ]]; then
  cat >&2 <<EOF
Missing local worker env file:
  $ENV_FILE

Create it from:
  docs/env.worker.local.example

Then fill ADMIN_DATABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and MIMO_API_KEY.
EOF
  exit 2
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

cd "$ROOT_DIR"
python3 -m bonus_platform.worker.main \
  --require-ready \
  --probe \
  --interval "$INTERVAL" \
  --worker-id "$WORKER_ID" \
  "$@"
