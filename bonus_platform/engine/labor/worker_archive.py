from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from .blob_storage import canonicalize_labor_metadata_for_blob, materialize_labor_metadata_for_local
from .runs import labor_run_metadata_lock


MAX_ARCHIVE_FILES = 1000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
RESULT_METADATA_FIELDS = {
    "status", "stage", "progress", "asyncTask", "summary", "result", "comparison",
    "pdfTotals", "excelTotals", "warehouseResults", "employeeResults", "quality",
    "extractionQuality", "reconciliationDiagnostics", "invoiceEvidenceAudit",
    "comparisonSummary", "comparisonRows", "candidateMatches", "warehouseComparison",
    "costSummaries", "batchGuard", "pdfExtractedRows", "excelRows", "reviewQueues",
    "structureReconciliation",
    "report", "businessReport", "projectionReport", "governanceReport", "files",
    "errorMessage", "errorCode", "failureType", "retryable", "requiresReupload",
    "machineCheckStatus", "nextAction", "diffDownloadUrl", "businessReportDownloadUrl", "completedAt", "updatedAt",
    "resultInputFingerprint",
}
SERVER_INPUT_FILE_FIELDS = {"pdfInvoices", "workbooks", "workbook"}


class LaborWorkerArchiveError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "worker_result_archive_invalid",
        formal_result_rejected: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "worker_result_archive_invalid")
        self.formal_result_rejected = bool(formal_result_rejected)


def build_worker_input_archive(run_dir: Path, *, expected_task_generation_id: str = "") -> bytes:
    if not run_dir.is_dir():
        raise FileNotFoundError("海外劳务批次不存在。")
    with labor_run_metadata_lock(run_dir.name):
        _assert_expected_generation(_load_result_metadata(run_dir), expected_task_generation_id)
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(run_dir.rglob("*")):
                if path.is_file() and not path.name.endswith(".tmp"):
                    archive.write(path, path.relative_to(run_dir).as_posix())
        return buffer.getvalue()


def merge_worker_result_archive(
    run_dir: Path,
    payload: bytes,
    *,
    expected_task_generation_id: str = "",
) -> list[str]:
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as exc:
        raise LaborWorkerArchiveError("Worker 结果包不是有效 ZIP 文件。") from exc
    staging_root: Path | None = None
    with archive, labor_run_metadata_lock(run_dir.name):
        current_metadata = _load_result_metadata(run_dir)
        _assert_expected_generation(current_metadata, expected_task_generation_id)
        validated_entries = _validate_archive_entries(archive)
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_root = Path(
            tempfile.mkdtemp(prefix=f".{run_dir.name}.worker-result-", dir=run_dir.parent)
        )
        try:
            staged_entries = _stage_archive_entries(archive, validated_entries, staging_root)
            incoming_metadata = [
                _parse_result_metadata(staged_path.read_bytes())
                for relative, staged_path in staged_entries
                if relative == Path("metadata.json")
            ]
            merged: list[str] = []
            staged_files: dict[Path, Path] = {}
            for relative, staged_path in staged_entries:
                if relative == Path("metadata.json"):
                    merged.append("metadata.json")
                    continue
                destination = run_dir / relative
                if _is_protected_input(destination, run_dir):
                    continue
                staged_files[relative] = staged_path
                merged.append(relative.as_posix())

            prepared_metadata = _prepare_result_metadata(
                run_dir,
                incoming_metadata,
                staged_files,
                expected_task_generation_id=expected_task_generation_id,
                current=current_metadata,
            )
            if prepared_metadata is not None:
                staged_metadata = staging_root / "prepared-metadata.json"
                staged_metadata.write_bytes(prepared_metadata)
                staged_files[Path("metadata.json")] = staged_metadata

            _validate_commit_targets(run_dir, staged_files)
            _commit_staged_files(run_dir, staged_files, staging_root / "backups")
            return merged
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)


def _safe_relative_path(name: str) -> Path:
    pure = PurePosixPath(str(name).replace("\\", "/"))
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise LaborWorkerArchiveError("Worker 结果包包含非法文件路径。")
    return Path(*pure.parts)


def _validate_archive_entries(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, Path]]:
    entries: list[tuple[zipfile.ZipInfo, Path]] = []
    normalized_paths: set[str] = set()
    for entry in archive.infolist():
        relative = _safe_relative_path(entry.filename)
        normalized = relative.as_posix().casefold()
        if normalized in normalized_paths:
            raise LaborWorkerArchiveError("Worker 结果包包含重复的文件路径。")
        normalized_paths.add(normalized)
        if not entry.is_dir():
            entries.append((entry, relative))
    if len(entries) > MAX_ARCHIVE_FILES:
        raise LaborWorkerArchiveError("Worker 结果包文件数量超过限制。")
    if sum(entry.file_size for entry, _ in entries) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        raise LaborWorkerArchiveError("Worker 结果包解压后大小超过限制。")
    file_paths = {tuple(part.casefold() for part in relative.parts) for _, relative in entries}
    for parts in file_paths:
        if any(parts[:index] in file_paths for index in range(1, len(parts))):
            raise LaborWorkerArchiveError("Worker 结果包包含冲突的文件路径。")
    return entries


def _stage_archive_entries(
    archive: zipfile.ZipFile,
    entries: list[tuple[zipfile.ZipInfo, Path]],
    staging_root: Path,
) -> list[tuple[Path, Path]]:
    entries_dir = staging_root / "entries"
    entries_dir.mkdir()
    staged_entries: list[tuple[Path, Path]] = []
    staged_bytes = 0
    for index, (entry, relative) in enumerate(entries):
        staged_path = entries_dir / str(index)
        try:
            with archive.open(entry) as source, staged_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        except (EOFError, NotImplementedError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise LaborWorkerArchiveError("Worker 结果包包含无法读取的文件。") from exc
        actual_size = staged_path.stat().st_size
        staged_bytes += actual_size
        if actual_size != entry.file_size or staged_bytes > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise LaborWorkerArchiveError("Worker 结果包解压后大小与清单不一致。")
        staged_entries.append((relative, staged_path))
    return staged_entries


def _is_protected_input(path: Path, run_dir: Path) -> bool:
    if not path.exists():
        return False
    if path.suffix.lower() == ".pdf":
        return True
    metadata_path = run_dir / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}
    protected = set()
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    for key in ("pdfInvoices", "workbooks"):
        records = files.get(key) if isinstance(files.get(key), list) else []
        protected.update(Path(str(record.get("path") or record.get("filename") or "")).name for record in records if isinstance(record, dict))
    return path.name in protected


def _parse_result_metadata(content: bytes) -> dict[str, Any]:
    try:
        incoming = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LaborWorkerArchiveError("Worker 结果 metadata.json 无效。") from exc
    if not isinstance(incoming, dict):
        raise LaborWorkerArchiveError("Worker 结果 metadata.json 必须是对象。")
    return incoming


def _load_result_metadata(run_dir: Path) -> dict[str, Any] | None:
    metadata_path = run_dir / "metadata.json"
    try:
        content = metadata_path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LaborWorkerArchiveError("现有 metadata.json 无法读取。") from exc
    try:
        metadata = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LaborWorkerArchiveError("现有 metadata.json 无效。") from exc
    if not isinstance(metadata, dict):
        raise LaborWorkerArchiveError("现有 metadata.json 必须是对象。")
    return metadata


def _prepare_result_metadata(
    run_dir: Path,
    incoming_metadata: list[dict[str, Any]],
    archive_files: dict[Path, Path],
    *,
    expected_task_generation_id: str = "",
    current: dict[str, Any] | None = None,
) -> bytes | None:
    if current is None:
        current = _load_result_metadata(run_dir)
    metadata = current or {}
    incoming = incoming_metadata[0] if incoming_metadata else None
    rejection = _worker_result_rejection(
        current,
        incoming,
        archive_files,
        expected_task_generation_id=expected_task_generation_id,
    )
    if rejection is not None:
        reason_code, message = rejection
        raise LaborWorkerArchiveError(
            message,
            code=reason_code,
            formal_result_rejected=True,
        )
    if incoming is None:
        raise LaborWorkerArchiveError(
            "Worker 结果 metadata.json 不完整，不能发布为正式机器核对结果。",
            code="worker_result_metadata_incomplete",
            formal_result_rejected=True,
        )
    _invalidate_official_result(
        metadata,
        reason_code="worker_result_replaced",
        message="已接收新的完整 Worker 核对结果。",
    )
    current_files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}
    for key in RESULT_METADATA_FIELDS - {"files"}:
        if key in incoming:
            metadata[key] = incoming[key]
    metadata["files"] = _merge_worker_result_files(current_files, incoming["files"])
    # Worker output is machine evidence. Business approval and payment policy
    # remain server-owned and reset whenever a new result archive is merged.
    metadata.update(
        {
            "businessReviewStatus": "pending",
            "manualReviewRequired": True,
            "directPaymentAllowed": False,
            "requiresHumanReview": True,
        }
    )
    canonical = canonicalize_labor_metadata_for_blob(run_dir, metadata)
    materialized = materialize_labor_metadata_for_local(run_dir, canonical)
    return json.dumps(materialized, ensure_ascii=False, indent=2).encode("utf-8")


def _worker_result_rejection(
    current: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
    archive_files: dict[Path, Path],
    *,
    expected_task_generation_id: str = "",
) -> tuple[str, str] | None:
    if incoming is None:
        return (
            "worker_result_metadata_missing",
            "Worker 结果包缺少 metadata.json，不能沿用旧机器核对结论，必须重新执行完整核对。",
        )
    if current is None:
        return (
            "worker_result_server_metadata_missing",
            "服务端缺少当前批次 metadata.json，不能接纳 Worker 正式结果。",
        )
    expected_generation = str(expected_task_generation_id or "").strip()
    if expected_generation and str(incoming.get("taskGenerationId") or "").strip() != expected_generation:
        return (
            "worker_result_generation_mismatch",
            "Worker 结果不属于当前任务代次，不能写入当前批次。",
        )
    incoming_files = incoming.get("files") if isinstance(incoming.get("files"), dict) else {}
    diff_report = incoming_files.get("diffReport") if isinstance(incoming_files.get("diffReport"), dict) else {}
    report_size = diff_report.get("sizeBytes")
    if isinstance(report_size, int) and not isinstance(report_size, bool) and report_size <= 0:
        return (
            "worker_result_report_empty",
            "Worker 差异报告为空文件，不能发布正式结果。",
        )
    if not _is_complete_worker_result_metadata(incoming, archive_files):
        return (
            "worker_result_metadata_incomplete",
            "Worker 结果 metadata.json 不完整或缺少对应报告，不能发布为正式机器核对结果。",
        )
    if not _worker_report_integrity_matches(incoming, archive_files):
        return (
            "worker_result_report_integrity_mismatch",
            "Worker 差异报告的大小或 SHA-256 与结果清单不一致，不能发布正式结果。",
        )
    if incoming["resultInputFingerprint"] != _result_input_fingerprint(current):
        return (
            "worker_result_input_mismatch",
            "Worker 结果对应的 PDF、Excel、字段映射或治理版本与服务端当前输入不一致，必须重新执行完整核对。",
        )
    return None


def _is_complete_worker_result_metadata(incoming: dict[str, Any], archive_files: dict[Path, Path]) -> bool:
    required_types = {
        "status": str,
        "comparisonSummary": dict,
        "comparisonRows": list,
        "candidateMatches": list,
        "warehouseComparison": dict,
        "extractionQuality": dict,
        "reconciliationDiagnostics": dict,
        "costSummaries": list,
        "invoiceEvidenceAudit": list,
        "reviewQueues": dict,
        "structureReconciliation": dict,
        "batchGuard": dict,
        "pdfExtractedRows": list,
        "excelRows": list,
        "files": dict,
        "machineCheckStatus": str,
        "diffDownloadUrl": str,
        "resultInputFingerprint": str,
    }
    if any(key not in incoming or not isinstance(incoming[key], expected) for key, expected in required_types.items()):
        return False
    summary = incoming["comparisonSummary"]
    batch_guard = incoming["batchGuard"]
    diagnostics = incoming["reconciliationDiagnostics"]
    fingerprint = incoming["resultInputFingerprint"].strip().lower()
    if (
        not incoming["status"].strip()
        or not isinstance(summary.get("canRelease"), bool)
        or not str(summary.get("conclusionLevel") or "").strip()
        or not str(incoming["machineCheckStatus"] or "").strip()
        or not str(batch_guard.get("status") or "").strip()
        or not isinstance(batch_guard.get("allowReleasableReport"), bool)
        or not str(diagnostics.get("level") or "").strip()
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        return False
    diff_report = incoming["files"].get("diffReport")
    if not isinstance(diff_report, dict):
        return False
    filename = Path(str(diff_report.get("filename") or "")).name
    report_download_url = str(diff_report.get("downloadUrl") or "").strip()
    report_sha256 = str(diff_report.get("sha256") or "").strip().lower()
    report_size = diff_report.get("sizeBytes")
    if (
        not filename
        or not report_download_url
        or str(incoming["diffDownloadUrl"] or "").strip() != report_download_url
        or not isinstance(report_size, int)
        or isinstance(report_size, bool)
        or report_size <= 0
        or len(report_sha256) != 64
        or any(character not in "0123456789abcdef" for character in report_sha256)
        or Path(filename) not in archive_files
    ):
        return False
    return True


def _worker_report_integrity_matches(incoming: dict[str, Any], archive_files: dict[Path, Path]) -> bool:
    diff_report = incoming.get("files", {}).get("diffReport", {})
    filename = Path(str(diff_report.get("filename") or "")).name
    staged = archive_files.get(Path(filename))
    if staged is None:
        return False
    if staged.stat().st_size != int(diff_report.get("sizeBytes") or 0):
        return False
    digest = hashlib.sha256()
    with staged.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == str(diff_report.get("sha256") or "").strip().lower()


def _assert_expected_generation(
    metadata: dict[str, Any] | None,
    expected_task_generation_id: str,
) -> None:
    expected = str(expected_task_generation_id or "").strip()
    current = metadata if isinstance(metadata, dict) else {}
    async_task = current.get("asyncTask") if isinstance(current.get("asyncTask"), dict) else {}
    actual = str(current.get("taskGenerationId") or async_task.get("taskGenerationId") or "").strip()
    if actual != expected:
        raise LaborWorkerArchiveError(
            "Worker 任务代次已失效，结果不能写入当前批次。",
            code="worker_result_generation_mismatch",
            formal_result_rejected=True,
        )


def _merge_worker_result_files(current_files: dict[str, Any], incoming_files: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current_files)
    for key, value in incoming_files.items():
        if key not in SERVER_INPUT_FILE_FIELDS:
            merged[key] = value
    return merged


def _result_input_fingerprint(metadata: dict[str, Any]) -> str:
    files = metadata.get("files") if isinstance(metadata.get("files"), dict) else {}

    def stable_file_records(key: str) -> list[dict[str, Any]]:
        records = files.get(key) if isinstance(files.get(key), list) else []
        return [
            {
                str(field): value
                for field, value in record.items()
                if field not in {"path", "downloadUrl", "url"}
            }
            for record in records
            if isinstance(record, dict)
        ]

    active_governance: dict[str, list[Any]] = {}
    for governance_key, active_key in (
        ("ruleGovernance", "activeRules"),
        ("nameMappingGovernance", "activeMappings"),
        ("allocationGovernance", "activeAllocations"),
        ("profileGovernance", "activeProfiles"),
        ("correctionGovernance", "activeCorrections"),
        ("reocrReplayGovernance", "activeCandidates"),
    ):
        governance = metadata.get(governance_key) if isinstance(metadata.get(governance_key), dict) else {}
        active_governance[governance_key] = (
            governance.get(active_key) if isinstance(governance.get(active_key), list) else []
        )

    fingerprint_payload = {
        "supplierName": str(metadata.get("supplierName") or metadata.get("supplier") or ""),
        "periodStart": str(metadata.get("periodStart") or ""),
        "periodEnd": str(metadata.get("periodEnd") or ""),
        "currency": str(metadata.get("currency") or ""),
        "reconciliationScope": str(metadata.get("reconciliationScope") or "employee_detail_required"),
        "pdfInvoices": stable_file_records("pdfInvoices"),
        "workbooks": stable_file_records("workbooks"),
        "workbookSheet": str(metadata.get("workbookSheet") or ""),
        "excelMapping": metadata.get("excelMapping") if isinstance(metadata.get("excelMapping"), dict) else {},
        "workbookMappings": metadata.get("workbookMappings") if isinstance(metadata.get("workbookMappings"), list) else [],
        "manualNameMapping": metadata.get("manualNameMapping") if isinstance(metadata.get("manualNameMapping"), dict) else {},
        "activeGovernance": active_governance,
    }
    encoded = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _invalidate_official_result(
    metadata: dict[str, Any],
    *,
    reason_code: str,
    message: str,
) -> None:
    files = dict(metadata.get("files")) if isinstance(metadata.get("files"), dict) else {}
    files.pop("diffReport", None)
    files.pop("businessReport", None)
    metadata.update(
        {
            "files": files,
            "summary": {},
            "result": {},
            "comparison": {},
            "pdfTotals": [],
            "excelTotals": [],
            "warehouseResults": [],
            "employeeResults": [],
            "quality": {},
            "extractionQuality": {},
            "invoiceEvidenceAudit": [],
            "comparisonSummary": {},
            "comparisonRows": [],
            "candidateMatches": [],
            "warehouseComparison": {},
            "costSummaries": [],
            "pdfExtractedRows": [],
            "excelRows": [],
            "reviewQueues": {},
            "structureReconciliation": {},
            "report": {},
            "businessReport": {},
            "projectionReport": {},
            "governanceReport": {},
            "batchGuard": {
                "status": reason_code,
                "message": message,
                "allowReleasableReport": False,
                "unresolvedFiles": [],
            },
            "reconciliationDiagnostics": {
                "level": "warning",
                "message": message,
                "issues": [
                    {
                        "code": reason_code,
                        "level": "warning",
                        "message": message,
                    }
                ],
            },
            "resultInputFingerprint": "",
            "machineCheckStatus": "needs_review",
            "diffDownloadUrl": "",
            "businessReportDownloadUrl": "",
            "completedAt": "",
        }
    )


def _validate_commit_targets(run_dir: Path, staged_files: dict[Path, Path]) -> None:
    if run_dir.exists() and (not run_dir.is_dir() or run_dir.is_symlink()):
        raise LaborWorkerArchiveError("Worker 结果目录无效。")
    paths = set(staged_files)
    for relative in paths:
        for parent in relative.parents:
            if parent == Path("."):
                break
            if parent in paths:
                raise LaborWorkerArchiveError("Worker 结果包包含冲突的文件路径。")
        destination = run_dir / relative
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise LaborWorkerArchiveError("Worker 结果包目标路径无效。")
        current = run_dir
        for part in relative.parts[:-1]:
            current /= part
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                raise LaborWorkerArchiveError("Worker 结果包目标路径无效。")


def _commit_staged_files(run_dir: Path, staged_files: dict[Path, Path], backup_root: Path) -> None:
    if not staged_files:
        return
    run_dir_existed = run_dir.exists()
    created_directories: list[Path] = []
    operations: list[tuple[Path, Path | None]] = []
    try:
        if not run_dir_existed:
            run_dir.mkdir(parents=True)
            created_directories.append(run_dir)
        backup_root.mkdir(parents=True)
        for index, (relative, staged_path) in enumerate(staged_files.items()):
            destination = run_dir / relative
            current = run_dir
            for part in relative.parts[:-1]:
                current /= part
                if not current.exists():
                    current.mkdir()
                    created_directories.append(current)
            backup_path: Path | None = None
            if destination.exists():
                backup_path = backup_root / str(index)
                os.replace(destination, backup_path)
            operations.append((destination, backup_path))
            os.replace(staged_path, destination)
    except Exception as exc:
        rollback_errors: list[Exception] = []
        for destination, backup_path in reversed(operations):
            try:
                if destination.is_file() or destination.is_symlink():
                    destination.unlink()
                if backup_path is not None and backup_path.exists():
                    os.replace(backup_path, destination)
            except Exception as rollback_exc:  # noqa: BLE001 - best-effort transactional rollback.
                rollback_errors.append(rollback_exc)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        if rollback_errors:
            raise LaborWorkerArchiveError("Worker 结果包写入失败，且无法完整回滚。") from exc
        if isinstance(exc, LaborWorkerArchiveError):
            raise
        raise LaborWorkerArchiveError("Worker 结果包写入失败。") from exc
