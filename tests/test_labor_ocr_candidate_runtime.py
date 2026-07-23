import sys

from bonus_platform.engine.labor.models import LaborLineItem
from bonus_platform.engine.labor.ocr_candidate_runtime import evaluate_ocr_candidate_result, run_ocr_candidate_command


def test_runtime_returns_unavailable_when_command_is_empty(tmp_path):
    result = run_ocr_candidate_command([tmp_path / "invoice.pdf"], command="")

    assert result["status"] == "unavailable"
    assert result["rows"] == []


def test_runtime_uses_manifest_output_protocol(tmp_path):
    worker = tmp_path / "fake_worker.py"
    worker.write_text(
        "import argparse, json\n"
        "p=argparse.ArgumentParser(); p.add_argument('--input-manifest'); p.add_argument('--output-json'); a=p.parse_args()\n"
        "m=json.load(open(a.input_manifest))\n"
        "json.dump({'status':'completed','rows':[{'employee_name_raw':'Jane Doe','hours':8,'amount':80}],"
        "'files':m['pdfFiles']},open(a.output_json,'w'))\n",
        encoding="utf-8",
    )
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    result = run_ocr_candidate_command(
        [pdf_path],
        command=f'"{sys.executable}" "{worker}"',
        supplier="Unknown",
        currency="USD",
        timeout_seconds=10,
    )

    assert result["status"] == "completed"
    assert result["rows"][0]["employee_name_raw"] == "Jane Doe"
    assert result["manifest"]["supplier"] == "Unknown"


def test_runtime_polls_worker_progress_before_completion(tmp_path):
    worker = tmp_path / "progress_worker.py"
    worker.write_text(
        "import argparse,json,time\n"
        "from pathlib import Path\n"
        "p=argparse.ArgumentParser();p.add_argument('--input-manifest');p.add_argument('--output-json');a=p.parse_args()\n"
        "m=json.load(open(a.input_manifest));progress=Path(m['progressFile'])\n"
        "progress.write_text(json.dumps({'status':'running','processedPages':1,'totalPages':2}),encoding='utf-8')\n"
        "time.sleep(0.2)\n"
        "progress.write_text(json.dumps({'status':'running','processedPages':2,'totalPages':2}),encoding='utf-8')\n"
        "time.sleep(0.2)\n"
        "Path(a.output_json).write_text(json.dumps({'status':'completed','rows':[],'files':[]}),encoding='utf-8')\n",
        encoding="utf-8",
    )
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    snapshots = []

    result = run_ocr_candidate_command(
        [pdf_path],
        command=f'"{sys.executable}" "{worker}"',
        timeout_seconds=10,
        progress_callback=lambda payload: snapshots.append(payload),
    )

    assert result["status"] == "completed"
    assert [item["processedPages"] for item in snapshots] == [1, 2]


def test_evaluation_auto_accepts_only_closed_and_strictly_confirmed_candidate():
    result = {
        "status": "completed",
        "rows": [{"employee_name_raw": "Jane Doe", "source_file": "invoice.pdf", "hours": 8, "amount": 80}],
        "files": [{"sourceFile": "invoice.pdf", "failedPageCount": 0}],
    }
    excel = [LaborLineItem(source_type="offline_workbook", source_file="bill.xlsx", source_page_or_row="r1", employee_id="", employee_name_raw="Jane Doe", hours=8, amount=80)]

    evaluation = evaluate_ocr_candidate_result(result, excel, {"invoice.pdf": 80.0}, amount_tolerance=0.1)

    assert evaluation["decision"] == "auto_accept"
    assert evaluation["safeToUse"] is True


def test_evaluation_blocks_spelling_review_even_when_amount_closes():
    result = {
        "status": "completed",
        "rows": [{"employee_name_raw": "Deisy Rozo Panche", "source_file": "invoice.pdf", "hours": 8, "amount": 80}],
        "files": [{"sourceFile": "invoice.pdf", "failedPageCount": 0}],
    }
    excel = [LaborLineItem(source_type="offline_workbook", source_file="bill.xlsx", source_page_or_row="r1", employee_id="", employee_name_raw="Deisi Pozo", hours=8, amount=80)]

    evaluation = evaluate_ocr_candidate_result(result, excel, {"invoice.pdf": 80.0}, amount_tolerance=0.1)

    assert evaluation["decision"] == "needs_review"
    assert evaluation["safeToUse"] is False
    assert "strict_name_review_required" in evaluation["blockers"]
