from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bonus_platform.engine.labor.ocr_candidate_adapter import OcrPageResult, run_ocr_image
from bonus_platform.engine.labor.ocr_candidate_rows import extract_rows_from_visual_pages
from bonus_platform.engine.labor.hardening import LaborHardeningPolicy
from bonus_platform.engine.labor.ocr_worker_cache import cleanup_ocr_cache, labor_ocr_cache_dir, load_cached_pdf, pdf_content_digest, store_cached_pdf
from bonus_platform.engine.labor.extract import _warehouse_id_from_filename, _warehouse_id_from_text
from bonus_platform.engine.labor.parsing import parse_number


_EXPLICIT_TOTAL_RE = re.compile(
    r"^\s*(?P<label>GRAND\s+TOTAL|INVOICE\s+TOTAL|TOTAL\s+DUE|AMOUNT\s+DUE|TOTAL\s+TTC|TOTAL)"
    r"\s*:?\s*(?P<prefix>[$€£]|S|USD|EUR|GBP)?\s*"
    r"(?P<amount>\(?-?\d[\d ,.]*[.,]\d{2}\)?)\s*"
    r"(?P<suffix>USD|EUR|GBP)?\s*$",
    re.IGNORECASE,
)


def _cache_dir(manifest: dict[str, Any]) -> Path:
    configured = str(manifest.get("cacheDir") or os.environ.get("LABOR_OCR_CACHE_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return labor_ocr_cache_dir()


def _rebind_cached_payload(payload: dict[str, Any], source_file: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    for cached_row in payload.get("rows", []):
        row = dict(cached_row)
        row["source_file"] = source_file
        rows.append(row)
    file_payload = dict(payload.get("file") or {})
    file_payload["sourceFile"] = source_file
    file_payload["cacheHit"] = True
    return rows, file_payload


def _write_progress(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.flush()
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _extract_explicit_total_evidence(pages: list[OcrPageResult]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for page in pages:
        if page.error:
            continue
        for raw_line in page.visual_text.splitlines():
            line = " ".join(raw_line.split())
            match = _EXPLICIT_TOTAL_RE.match(line)
            if not match:
                continue
            label = " ".join(match.group("label").upper().split())
            currency = str(match.group("prefix") or match.group("suffix") or "").upper()
            if currency == "S":
                currency = "$"
            # A bare ``TOTAL 8.00`` is common in supporting time sheets and may
            # describe hours. The generic label is authoritative only when the
            # line also carries a currency marker.
            if label == "TOTAL" and not currency:
                continue
            amount = round(parse_number(match.group("amount")), 2)
            if amount <= 0:
                continue
            candidates.append(
                {
                    "page": page.page_number,
                    "label": label,
                    "amount": amount,
                    "currency": currency,
                    "evidenceText": line,
                }
            )
    distinct_amounts = sorted({float(item["amount"]) for item in candidates})
    payload: dict[str, Any] = {"explicitTotalCandidates": candidates}
    if len(distinct_amounts) == 1:
        selected = next(item for item in candidates if float(item["amount"]) == distinct_amounts[0])
        payload["explicitTotalAmount"] = distinct_amounts[0]
        payload["explicitTotalEvidence"] = selected
    else:
        payload["explicitTotalAmount"] = 0.0
        payload["explicitTotalEvidence"] = {}
    return payload


def process_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    all_rows = []
    files = []
    cache_dir = _cache_dir(manifest)
    policy = LaborHardeningPolicy.from_env()
    cleanup_before = cleanup_ocr_cache(
        cache_dir,
        retention_days=policy.ocr_cache_retention_days,
        max_bytes=policy.ocr_cache_max_bytes,
    )
    raw_paths = list(manifest.get("pdfFiles", []))
    progress_path = Path(str(manifest.get("progressFile"))).expanduser() if manifest.get("progressFile") else None
    progress = {
        "status": "running",
        "currentFile": "",
        "totalFiles": len(raw_paths),
        "processedFiles": 0,
        "totalPages": 0,
        "processedPages": 0,
        "cacheHitCount": 0,
        "message": f"开始识别 {len(raw_paths)} 张 PDF 发票。",
    }

    def publish(**updates: Any) -> None:
        progress.update(updates)
        if progress_path is not None:
            _write_progress(progress_path, progress)

    publish()
    for raw_path in raw_paths:
        path = Path(str(raw_path)).expanduser()
        publish(currentFile=path.name, message=f"正在检查 {path.name} 的本地 OCR 缓存。")
        content_digest = pdf_content_digest(path)
        cached = load_cached_pdf(cache_dir, path)
        if cached is not None:
            cached_rows, cached_file = _rebind_cached_payload(cached, path.name)
            cached_file["contentDigest"] = content_digest
            all_rows.extend(cached_rows)
            files.append(cached_file)
            progress["processedFiles"] += 1
            progress["cacheHitCount"] += 1
            cached_pages = int(cached_file.get("pageCount") or 0)
            progress["processedPages"] += cached_pages
            progress["totalPages"] = max(int(progress["totalPages"]), int(progress["processedPages"]))
            publish(message=f"{path.name} 已命中本地 OCR 缓存。")
            continue
        pages_before = int(progress["processedPages"])

        def page_completed(_page: OcrPageResult, completed_pages: int, file_pages: int) -> None:
            publish(
                processedPages=pages_before + completed_pages,
                totalPages=max(int(progress["totalPages"]), pages_before + file_pages),
                message=f"正在识别 {path.name}：{completed_pages} / {file_pages} 页。",
            )

        pages = _ocr_pdf(path, page_callback=page_completed)
        visual_pages = [
            {"source_file": path.name, "page": page.page_number, "visualText": page.visual_text}
            for page in pages
            if not page.error
        ]
        rows = extract_rows_from_visual_pages(
            visual_pages,
            supplier=str(manifest.get("supplier") or ""),
            period_start=str(manifest.get("periodStart") or ""),
            period_end=str(manifest.get("periodEnd") or ""),
            currency=str(manifest.get("currency") or ""),
        )
        page_text = "\n".join(page.visual_text for page in pages if not page.error)
        warehouse_id = _warehouse_id_from_text(page_text) or _warehouse_id_from_filename(path.name)
        file_rows = []
        for row in rows:
            payload = row.to_dict()
            payload["warehouse_id"] = payload.get("warehouse_id") or warehouse_id
            file_rows.append(payload)
            all_rows.append(payload)
        file_payload = {
            "sourceFile": path.name,
            "pageCount": len(pages),
            "successfulPageCount": sum(1 for page in pages if not page.error),
            "failedPageCount": sum(1 for page in pages if page.error),
            "candidateRowCount": len(rows),
            "candidateAmountTotal": round(sum(row.amount for row in rows), 2),
            "errors": [page.error for page in pages if page.error],
            "cacheHit": False,
            "contentDigest": content_digest,
            **_extract_explicit_total_evidence(pages),
        }
        files.append(file_payload)
        if not file_payload["failedPageCount"]:
            store_cached_pdf(
                cache_dir,
                path,
                {"status": "completed", "rows": file_rows, "file": file_payload},
            )
        progress["processedFiles"] += 1
        progress["processedPages"] = pages_before + len(pages)
        progress["totalPages"] = max(int(progress["totalPages"]), int(progress["processedPages"]))
        publish(message=f"{path.name} 识别完成。")
    failed = sum(int(item["failedPageCount"]) for item in files)
    result = {
        "status": "completed_with_errors" if failed else "completed",
        "candidateOnly": True,
        "rows": all_rows,
        "files": files,
        "summary": {
            "fileCount": len(files),
            "rowCount": len(all_rows),
            "failedPageCount": failed,
            "candidateAmountTotal": round(sum(float(row.get("amount") or 0) for row in all_rows), 2),
        },
    }
    cleanup_after = cleanup_ocr_cache(
        cache_dir,
        retention_days=policy.ocr_cache_retention_days,
        max_bytes=policy.ocr_cache_max_bytes,
    )
    result["cacheCleanup"] = {"before": cleanup_before, "after": cleanup_after}
    publish(
        status=result["status"],
        currentFile="",
        message="本地 OCR 识别完成。" if not failed else "本地 OCR 识别完成，但存在失败页面。",
    )
    return result


def _ocr_pdf(
    path: Path,
    *,
    scale: float = 2.0,
    page_callback: Callable[[OcrPageResult, int, int], None] | None = None,
) -> list[OcrPageResult]:
    import pypdfium2 as pdfium

    results: list[OcrPageResult] = []
    document = pdfium.PdfDocument(str(path))
    try:
        with tempfile.TemporaryDirectory(prefix="labor-ocr-worker-") as temporary_dir:
            for index in range(len(document)):
                page = document[index]
                image_path = Path(temporary_dir) / f"page-{index + 1}.png"
                try:
                    page.render(scale=scale).to_pil().save(image_path)
                    results.append(run_ocr_image(image_path, "rapidocr", page_number=index + 1))
                except Exception as exc:
                    results.append(OcrPageResult("rapidocr", index + 1, (), 0.0, f"{type(exc).__name__}: {exc}"))
                finally:
                    page.close()
                if page_callback is not None:
                    page_callback(results[-1], index + 1, len(document))
    finally:
        document.close()
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an overseas-labor OCR candidate task")
    parser.add_argument("--input-manifest", required=True)
    parser.add_argument("--output-json", required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.input_manifest).read_text(encoding="utf-8"))
    result = process_manifest(manifest)
    Path(args.output_json).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
