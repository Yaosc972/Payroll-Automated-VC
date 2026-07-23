from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bonus_platform.engine.labor.ocr_candidate_adapter import (
    OcrPageResult,
    available_ocr_backends,
    run_ocr_image,
)
from bonus_platform.engine.labor.parser_compare import summarize_business_signals


def summarize_candidate_run(file_name: str, backend: str, pages: list[OcrPageResult]) -> dict[str, Any]:
    text = "\n".join(page.text for page in pages if page.text)
    errors = [{"page": page.page_number, "error": page.error} for page in pages if page.error]
    return {
        "file": file_name,
        "backend": backend,
        "pageCount": len(pages),
        "successfulPageCount": sum(1 for page in pages if not page.error),
        "failedPageCount": len(errors),
        "lineCount": sum(len(page.lines) for page in pages),
        "durationSeconds": round(sum(page.duration_seconds for page in pages), 4),
        "signals": summarize_business_signals(text),
        "errors": errors,
        "pages": [
            {
                "page": page.page_number,
                "durationSeconds": page.duration_seconds,
                "lineCount": len(page.lines),
                "text": page.text,
                "visualText": page.visual_text,
                "lines": [
                    {
                        "text": line.text,
                        "confidence": line.confidence,
                        "polygon": [list(point) for point in line.polygon],
                    }
                    for line in page.lines
                ],
                "error": page.error,
            }
            for page in pages
        ],
    }


def compare_materials(material_roots: list[Path], backends: list[str], *, scale: float = 2.0) -> dict[str, Any]:
    availability = available_ocr_backends()
    files = sorted({path for root in material_roots for path in root.rglob("*.pdf") if path.is_file()})
    results: list[dict[str, Any]] = []
    for pdf_path in files:
        for backend in backends:
            if not availability.get(backend, False):
                results.append(_unavailable_result(pdf_path.name, backend))
                continue
            results.append(_run_pdf(pdf_path, backend, scale=scale))
    return {
        "source": "labor_ocr_candidate_comparison",
        "formalFlowChanged": False,
        "materials": [str(root) for root in material_roots],
        "availableBackends": availability,
        "summary": {
            "fileCount": len(files),
            "backendCount": len(backends),
            "resultCount": len(results),
        },
        "results": results,
    }


def write_report(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ocr_candidate_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 海外劳务 OCR 候选比较",
        "",
        "正式核对链路未改变。以下结果只用于候选评估。",
        "",
        "| 后端 | 文件 | 成功页/总页 | 文本字符 | 金额 | 姓名 | 工时 | 用时(秒) |",
        "| --- | --- | ---: | ---: | --- | --- | --- | ---: |",
    ]
    for item in report["results"]:
        signals = item["signals"]
        lines.append(
            f"| {item['backend']} | {item['file']} | {item['successfulPageCount']}/{item['pageCount']} | "
            f"{signals['textCharacterCount']} | {'是' if signals['hasAmountSignal'] else '否'} | "
            f"{'是' if signals['hasEmployeeNameSignal'] else '否'} | "
            f"{'是' if signals['hasHoursSignal'] else '否'} | {item['durationSeconds']:.2f} |"
        )
    (output_dir / "OCR_CANDIDATE_COMPARISON.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_pdf(pdf_path: Path, backend: str, *, scale: float) -> dict[str, Any]:
    import pypdfium2 as pdfium

    pages: list[OcrPageResult] = []
    document = pdfium.PdfDocument(str(pdf_path))
    try:
        with tempfile.TemporaryDirectory(prefix="labor-ocr-") as temporary_dir:
            for index in range(len(document)):
                image_path = Path(temporary_dir) / f"page-{index + 1}.png"
                page = document[index]
                try:
                    page.render(scale=scale).to_pil().save(image_path)
                    pages.append(run_ocr_image(image_path, backend, page_number=index + 1))
                except Exception as exc:
                    pages.append(OcrPageResult(backend, index + 1, (), 0.0, f"{type(exc).__name__}: {exc}"))
                finally:
                    page.close()
    finally:
        document.close()
    return summarize_candidate_run(pdf_path.name, backend, pages)


def _unavailable_result(file_name: str, backend: str) -> dict[str, Any]:
    return {
        "file": file_name,
        "backend": backend,
        "pageCount": 0,
        "successfulPageCount": 0,
        "failedPageCount": 0,
        "lineCount": 0,
        "durationSeconds": 0.0,
        "signals": summarize_business_signals(""),
        "errors": [{"page": 0, "error": "backend is not installed"}],
        "pages": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare candidate OCR engines on labor invoices")
    parser.add_argument("--materials", action="append", required=True)
    parser.add_argument("--backend", action="append", dest="backends")
    parser.add_argument("--output-dir", default="outputs/labor_ocr_candidate_compare/latest")
    parser.add_argument("--scale", type=float, default=2.0)
    args = parser.parse_args(argv)
    report = compare_materials(
        [Path(value).expanduser() for value in args.materials],
        args.backends or ["rapidocr", "paddleocr"],
        scale=args.scale,
    )
    write_report(report, Path(args.output_dir).expanduser())
    print(Path(args.output_dir).expanduser() / "OCR_CANDIDATE_COMPARISON.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
