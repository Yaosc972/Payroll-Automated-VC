#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${SIGMA_WORKER_ENV_FILE:-$ROOT_DIR/.env.worker.local}"

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

export SIGMA_OVERSEAS_LABOR_ACCESS="${SIGMA_OVERSEAS_LABOR_ACCESS:-production}"
export SIGMA_LABOR_STORAGE_BACKEND="${SIGMA_LABOR_STORAGE_BACKEND:-supabase}"
export SIGMA_LABOR_STORAGE_ENV="${SIGMA_LABOR_STORAGE_ENV:-production}"
export SIGMA_LABOR_SUPABASE_BUCKET="${SIGMA_LABOR_SUPABASE_BUCKET:-sigma-labor-runs}"
export SIGMA_LABOR_EXECUTION_MODE="${SIGMA_LABOR_EXECUTION_MODE:-worker}"
export SIGMA_LABOR_JOB_BACKEND="${SIGMA_LABOR_JOB_BACKEND:-postgres}"

cd "$ROOT_DIR"
python3 -m bonus_platform.worker.main --check --probe
