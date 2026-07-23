#!/usr/bin/env python3
"""Read-only P1 deployment probe that delegates readiness to the application."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

import httpx


SCHEMA_VERSION = 1
_SAFE_CODE = re.compile(r"^[0-9A-Za-z_-]{1,128}$")


def normalize_base_url(value: str) -> str:
    candidate = str(value or "").strip().rstrip("/")
    parsed = urlparse(candidate)
    if not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("P1 preflight target must be an absolute URL without credentials.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("P1 preflight target must be an origin without path, query, or fragment.")
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("P1 preflight target must use HTTPS, except localhost development.")
    return f"{parsed.scheme}://{parsed.netloc}"


def run_preflight(
    base_url: str,
    *,
    operations_token: str = "",
    client: Any | None = None,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    target = normalize_base_url(base_url)
    if client is not None:
        return _run_preflight(target, operations_token=str(operations_token or ""), client=client)
    with httpx.Client(timeout=max(1.0, float(timeout_seconds)), follow_redirects=False) as owned_client:
        return _run_preflight(target, operations_token=str(operations_token or ""), client=owned_client)


def _run_preflight(target: str, *, operations_token: str, client: Any) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    blockers: list[dict[str, str]] = []

    def block(code: str, source: str) -> None:
        if not any(item["code"] == code for item in blockers):
            blockers.append({"code": code, "source": source})

    auth = _get(client, f"{target}/api/auth/feishu/config")
    if auth["statusCode"] == 200 and auth["payload"].get("configured") is True:
        checks.append({"id": "feishu_auth", "status": "passed", "configured": True})
    elif auth["statusCode"] == 404:
        checks.append({"id": "feishu_auth", "status": "stale", "configured": False})
        block("deployment_contract_stale", "feishu_auth")
    elif auth["statusCode"] == 200:
        checks.append({"id": "feishu_auth", "status": "blocked", "configured": False})
        block("feishu_auth_not_configured", "feishu_auth")
    else:
        checks.append(_failed_check("feishu_auth", auth))
        block("feishu_auth_probe_failed", "feishu_auth")

    access = _get(client, f"{target}/api/labor/access")
    access_payload = access["payload"]
    if access["statusCode"] != 200:
        checks.append(_failed_check("p1_contract", access))
        block("labor_access_probe_failed", "p1_contract")
    else:
        p1 = access_payload.get("p1") if isinstance(access_payload.get("p1"), Mapping) else {}
        runtime = (
            access_payload.get("runtimeGate")
            if isinstance(access_payload.get("runtimeGate"), Mapping)
            else {}
        )
        contract_ready = bool(
            p1.get("required") is True
            and p1.get("uploadMode") == "signed_private_direct"
        )
        runtime_current = runtime.get("runtimeSourceCurrent") is True
        checks.append(
            {
                "id": "p1_contract",
                "status": "passed" if contract_ready and runtime_current else "blocked",
                "observedVersion": str(access_payload.get("version") or "")[:40],
                "buildIdPresent": bool(str(access_payload.get("buildId") or "").strip()),
                "p1Required": bool(p1.get("required")),
                "uploadMode": str(p1.get("uploadMode") or "")[:64],
                "runtimeSourceCurrent": runtime_current,
            }
        )
        if not contract_ready:
            block("p1_mode_not_enabled", "p1_contract")
        if contract_ready and not runtime_current:
            block("runtime_source_not_current", "p1_contract")

    token = operations_token.strip()
    if not token:
        checks.append({"id": "production_readiness", "status": "skipped", "reason": "token_missing"})
        block("operations_token_missing", "production_readiness")
    else:
        readiness = _get(
            client,
            f"{target}/api/labor/production-readiness",
            headers={"x-admin-token": token},
        )
        readiness_payload = readiness["payload"]
        if readiness["statusCode"] == 200:
            p1 = (
                readiness_payload.get("p1")
                if isinstance(readiness_payload.get("p1"), Mapping)
                else {}
            )
            policy_safe = bool(
                readiness_payload.get("manualReviewRequired") is True
                and readiness_payload.get("directPaymentAllowed") is False
            )
            readiness_ready = bool(
                readiness_payload.get("status") == "ready_for_p1_integration"
                and p1.get("required") is True
                and p1.get("ready") is True
                and policy_safe
            )
            checks.append(
                {
                    "id": "production_readiness",
                    "status": "passed" if readiness_ready else "blocked",
                    "readinessStatus": str(readiness_payload.get("status") or "")[:64],
                    "p1Ready": bool(p1.get("ready")),
                    "manualReviewRequired": readiness_payload.get("manualReviewRequired") is True,
                    "directPaymentAllowed": readiness_payload.get("directPaymentAllowed") is True,
                }
            )
            raw_blockers = readiness_payload.get("blockers")
            if isinstance(raw_blockers, list):
                for item in raw_blockers[:64]:
                    code = str(item.get("code") or "") if isinstance(item, Mapping) else ""
                    if _SAFE_CODE.fullmatch(code):
                        block(code, "production_readiness")
            if not policy_safe:
                block("human_review_policy_required", "production_readiness")
            if not readiness_ready and not any(
                item["source"] == "production_readiness" for item in blockers
            ):
                block("p1_readiness_not_ready", "production_readiness")
        elif readiness["statusCode"] in {401, 403}:
            checks.append({"id": "production_readiness", "status": "blocked", "statusCode": readiness["statusCode"]})
            block("operations_token_invalid", "production_readiness")
        elif readiness["statusCode"] == 404:
            checks.append({"id": "production_readiness", "status": "stale", "statusCode": 404})
            block("deployment_contract_stale", "production_readiness")
        else:
            checks.append(_failed_check("production_readiness", readiness))
            block("production_readiness_probe_failed", "production_readiness")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "target": target,
        "ready": not blockers and all(item.get("status") == "passed" for item in checks),
        "checks": checks,
        "blockers": blockers,
        "nextActions": _next_actions(blockers),
    }


def _get(client: Any, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        response = client.get(url, headers=headers or {})
    except httpx.HTTPError as exc:
        return {"statusCode": 0, "payload": {}, "errorType": type(exc).__name__[:96]}
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = {}
    return {
        "statusCode": int(getattr(response, "status_code", 0) or 0),
        "payload": dict(payload) if isinstance(payload, Mapping) else {},
    }


def _failed_check(check_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "unreachable" if int(result.get("statusCode") or 0) == 0 else "blocked",
        "statusCode": int(result.get("statusCode") or 0),
        "errorType": str(result.get("errorType") or "")[:96],
    }


def _next_actions(blockers: Sequence[Mapping[str, str]]) -> list[str]:
    actions = {
        "deployment_contract_stale": "将当前 P1 候选发布到隔离 Preview，再重新执行预检。",
        "feishu_auth_not_configured": "在 UAT 配置现有飞书应用变量，不新增登录实现。",
        "p1_mode_not_enabled": "先补齐 Postgres、私有存储和 Worker 配置，再开启 P1 模式。",
        "operations_token_missing": "仅在本机环境变量中提供 UAT 运维 Token 后重试。",
        "operations_token_invalid": "核对 UAT 运维 Token 的环境范围并重新签发。",
    }
    rows = []
    for blocker in blockers:
        action = actions.get(str(blocker.get("code") or ""))
        if action and action not in rows:
            rows.append(action)
    if blockers and not rows:
        rows.append("按 production-readiness blockerCodes 修复 UAT 配置后重试。")
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only overseas labor P1 deployment preflight.")
    parser.add_argument("base_url", help="UAT origin, for example https://uat.example.com")
    parser.add_argument(
        "--operations-token-env",
        default="SIGMA_LABOR_OPERATIONS_TOKEN",
        help="Environment variable that contains the operations token; its value is never printed.",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON.")
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = run_preflight(
            args.base_url,
            operations_token=os.environ.get(args.operations_token_env, ""),
        )
    except ValueError as exc:
        print(json.dumps({"ready": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
