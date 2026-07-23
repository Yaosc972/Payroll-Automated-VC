from __future__ import annotations

import json
import re
from typing import Any, Mapping

from .worker_version import parse_stable_worker_version


def evaluate_labor_production_readiness(
    *,
    env: Mapping[str, str],
    storage_info: Mapping[str, Any],
    queue_health: Mapping[str, Any],
    build_info: Mapping[str, Any],
    auth_health: Mapping[str, Any] | None = None,
    state_health: Mapping[str, Any] | None = None,
    storage_health: Mapping[str, Any] | None = None,
    worker_identity_health: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return sanitized deployment prerequisites for controlled human-review UAT."""
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    p1_required = _truthy(env.get("SIGMA_LABOR_P1_REQUIRED"))

    if not storage_info.get("enabled") or storage_info.get("backend") not in {"blob", "supabase"}:
        blockers.append(_issue("persistent_storage_required", "必须配置 Blob 或 Supabase 持久化批次文件。"))
    if queue_health.get("backend") != "postgres" or not queue_health.get("ready"):
        blockers.append(_issue("postgres_queue_required", "Vercel 与本机 Worker 之间必须使用可用的 Postgres 队列。"))
    if not p1_required and not _valid_worker_tokens(env.get("SIGMA_LABOR_WORKER_TOKENS", "")):
        blockers.append(_issue("worker_tokens_required", "必须配置至少一个绑定用户和设备的 Worker 令牌。"))
    if not str(env.get("SIGMA_LABOR_OPERATIONS_TOKEN") or "").strip():
        blockers.append(_issue("operations_token_required", "必须配置运维接口访问令牌。"))
    if str(env.get("SIGMA_LABOR_EXECUTION_MODE") or "").strip().lower() not in {
        "personal-worker", "personal_worker", "desktop-worker", "desktop_worker"
    }:
        blockers.append(_issue("personal_worker_mode_required", "必须启用个人桌面 Worker 执行模式。"))
    if _truthy(env.get("SIGMA_LABOR_EXTERNAL_AI_ENABLED")):
        blockers.append(_issue("external_ai_disabled_required", "首轮 UAT 禁止把真实材料发送到外部 AI。"))
    raw_update_manifest = str(env.get("SIGMA_LABOR_WORKER_UPDATE_MANIFEST") or "").strip()
    required_worker_version = str(build_info.get("requiredWorkerVersion") or "0.3.0")
    if not raw_update_manifest:
        warnings.append(_issue("signed_update_manifest_missing", "尚未配置 Worker 签名更新清单。"))
    elif not _valid_update_manifest(raw_update_manifest, required_worker_version):
        warnings.append(_issue("signed_update_manifest_invalid", "Worker 更新清单的版本、HTTPS 地址、SHA-256 或签名不完整。"))
    if "SIGMA_LABOR_REQUIRE_CLIENT_CONTRACT" in env and not _truthy(
        env.get("SIGMA_LABOR_REQUIRE_CLIENT_CONTRACT")
    ):
        blockers.append(_issue("client_contract_required", "必须强制校验页面/API build 契约。"))
    if p1_required:
        auth = auth_health or {}
        state = state_health or {}
        signed_storage = storage_health or {}
        worker_identity = worker_identity_health or {}
        if not auth.get("ready"):
            blockers.append(_issue("trusted_auth_required", "必须启用飞书真实登录、Postgres 角色库和安全会话 Cookie。"))
        if state.get("backend") != "postgres" or not state.get("ready"):
            blockers.append(_issue("postgres_state_required", "批次、文件、映射、复核、任务和审计必须使用可用的 Postgres 权威状态库。"))
        if not (
            signed_storage.get("ready")
            and signed_storage.get("private")
            and signed_storage.get("directUpload")
            and signed_storage.get("directDownload")
        ):
            blockers.append(_issue("private_signed_storage_required", "私有对象存储必须通过读写删除探针，并支持短期直传直下。"))
        if worker_identity.get("backend") != "postgres" or not worker_identity.get("ready"):
            blockers.append(_issue("short_lived_worker_identity_required", "Worker 必须使用绑定用户和设备、可轮换可吊销的短期数据库令牌。"))
    warnings.append(
        _issue(
            "controlled_uat_gates_pending",
            (
                "P1 基础设施就绪后，仍需完成 Golden 全链路、签名 Worker 包和影子 UAT 闸门。"
                if p1_required
                else "当前接口仅覆盖开发预检；真实身份、完整状态库、在线 Worker、签名包和 Golden 硬门禁仍待实现。"
            ),
        )
    )
    build_status = str(build_info.get("status") or "unverified").strip().lower()
    if build_status != "current":
        blockers.append(
            _issue(
                "runtime_restart_required" if build_status == "restart_required" else "runtime_build_unverified",
                "海外劳务服务运行版本已变化，必须重启或重新部署后再开放受控 UAT。",
            )
        )

    sanitized_build = {
        key: build_info[key]
        for key in (
            "status",
            "buildId",
            "sourceRef",
            "processStartedAt",
            "startupFingerprint",
            "currentFingerprint",
            "fileCount",
            "missingSentinels",
            "apiContractVersion",
            "requiredWorkerVersion",
        )
        if key in build_info
    }

    p1_ready = bool(p1_required and not blockers)
    return {
        "status": "blocked" if blockers else "ready_for_p1_integration" if p1_required else "ready_for_developer_preview",
        "readinessLevel": "p1_infrastructure" if p1_required else "developer_preflight",
        "manualReviewRequired": True,
        "directPaymentAllowed": False,
        "blockers": blockers,
        "warnings": warnings,
        "storage": {
            "enabled": bool(storage_info.get("enabled")),
            "backend": str(storage_info.get("backend") or ""),
            "environment": str(storage_info.get("environment") or ""),
        },
        "queue": {
            "backend": str(queue_health.get("backend") or ""),
            "configured": bool(queue_health.get("configured")),
            "ready": bool(queue_health.get("ready")),
        },
        "p1": {
            "required": p1_required,
            "ready": p1_ready,
            "authReady": bool((auth_health or {}).get("ready")),
            "stateReady": bool((state_health or {}).get("ready")),
            "storageReady": bool((storage_health or {}).get("ready")),
            "workerIdentityReady": bool((worker_identity_health or {}).get("ready")),
        },
        "build": sanitized_build,
    }


def _valid_worker_tokens(raw: str) -> bool:
    try:
        tokens = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return False
    if not isinstance(tokens, dict) or not tokens:
        return False
    return all(
        isinstance(identity, dict) and identity.get("userId") and identity.get("deviceId")
        for identity in tokens.values()
    )


def _valid_update_manifest(raw: str, required_worker_version: str) -> bool:
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(manifest, dict):
        return False
    if not all(str(manifest.get(key) or "").strip() for key in ("version", "minimumVersion", "url", "sha256", "signature")):
        return False
    if not str(manifest["url"]).strip().startswith("https://"):
        return False
    if not re.fullmatch(r"[A-Fa-f0-9]{64}", str(manifest["sha256"]).strip()):
        return False
    try:
        version = parse_stable_worker_version(manifest["version"])
        minimum = parse_stable_worker_version(manifest["minimumVersion"])
        required = parse_stable_worker_version(required_worker_version)
    except ValueError:
        return False
    return version >= minimum >= required


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
