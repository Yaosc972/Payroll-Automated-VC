#!/bin/zsh
set -euo pipefail

umask 077

UAT_ROOT="/Users/zt27532/Library/Application Support/SigmaWorkbenchUAT"
APP_ROOT="$UAT_ROOT/app"
PYTHON_BIN="/usr/bin/python3"
NODE_BIN="/Users/zt27532/.local/bin/node"

required_paths=(
  "$APP_ROOT/bonus_platform/app.py"
  "$UAT_ROOT/engine/lib/beisen-client.mjs"
  "$UAT_ROOT/config/深圳社保批量人员参保登记模板.xls"
  "$UAT_ROOT/config/全部离职记录.xlsx"
  "$UAT_ROOT/logs"
  "$NODE_BIN"
)
for required_path in "${required_paths[@]}"; do
  if [[ ! -e "$required_path" ]]; then
    print -u2 "社保 UAT 启动失败：缺少 $required_path"
    exit 1
  fi
done

# launchd 在脚本执行前创建日志文件，启动后收紧权限。
chmod 600 "$UAT_ROOT/logs/app.log" "$UAT_ROOT/logs/app-error.log" 2>/dev/null || true

export SIGMA_SOCIAL_INSURANCE_RUNS_DIR="$UAT_ROOT/social_insurance_runs"
export SIGMA_SOCIAL_INSURANCE_BASELINES_DIR="$UAT_ROOT/social_insurance_baselines"
export SIGMA_SOCIAL_INSURANCE_SNAPSHOTS_DIR="$UAT_ROOT/social_insurance_baselines/snapshots"
export SIGMA_SOCIAL_INSURANCE_ENGINE_DIR="$UAT_ROOT/engine"
export SIGMA_SOCIAL_INSURANCE_TEMPLATE_FILE="$UAT_ROOT/config/深圳社保批量人员参保登记模板.xls"
export SIGMA_SOCIAL_INSURANCE_DIMISSION_FILE="$UAT_ROOT/config/全部离职记录.xlsx"
export SIGMA_SOCIAL_INSURANCE_NODE="$NODE_BIN"
export SIGMA_SOCIAL_INSURANCE_PREFETCH_ENABLED="true"
export SIGMA_SOCIAL_INSURANCE_PREFETCH_INTERVAL_MINUTES="120"
export SIGMA_SOCIAL_INSURANCE_PREFETCH_INTERACTIVE_DELAY_SECONDS="0"
export SIGMA_SOCIAL_INSURANCE_PREFETCH_STARTUP_DELAY_SECONDS="7200"

# 仅监听回环地址；Windows 必须通过受限 SSH 端口转发访问。
export SIGMA_LABOR_AUTH_REQUIRED="false"
export SIGMA_ENABLE_MOCK_LOGIN="false"

cd "$APP_ROOT"
# 接电时阻止主机自动休眠；显示器仍可按系统设置关闭。
exec /usr/bin/caffeinate -s "$PYTHON_BIN" -m uvicorn bonus_platform.app:app --host 127.0.0.1 --port 8001
