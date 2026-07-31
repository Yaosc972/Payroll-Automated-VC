from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FBU_JS = ROOT / "bonus_platform" / "static" / "fbu-performance.js"


def test_fbu_attendance_uses_supabase_direct_upload_flow():
    script = FBU_JS.read_text(encoding="utf-8")

    assert "/attendance-direct-upload-plan" in script
    assert "/attendance-direct-upload-complete" in script
    assert "uploadFbuFileToSignedUrl" in script
    assert "request.open('PUT', upload.signedUrl)" in script
    assert "uploadWorkbenchAttendanceFilesDirect" in script


def test_all_run_materials_use_persisted_direct_upload_jobs_with_polling_and_resume():
    script = FBU_JS.read_text(encoding="utf-8")

    for marker in [
        "uploadWorkbenchFilesDirect",
        "/uploads/plan",
        "/start",
        "pollFbuUploadJob",
        "restoreFbuUploadJobs",
        "activeFbuUploadJobs",
        "localStorage",
        "正在排队",
        "正在解析",
    ]:
        assert marker in script

    salary_area = script.split("async function uploadWorkbenchSalaryHistoryMaterial(type, file)", 1)[1].split(
        "async function confirmSalaryVerification", 1
    )[0]
    assert "uploadWorkbenchFilesDirect" in salary_area
    assert "new FormData()" not in salary_area


def test_calculation_uses_persisted_background_job_status():
    script = FBU_JS.read_text(encoding="utf-8")
    calculate_area = script.split("async function executeCalculate", 1)[1].split(
        "el.btnCalculate", 1
    )[0]

    assert "/calculation-jobs" in calculate_area
    assert "pollFbuCalculationJob" in calculate_area
    assert "/calculate/" not in calculate_area
    assert "正在核算" in script


def test_job_polling_skips_redundant_full_workbench_renders():
    script = FBU_JS.read_text(encoding="utf-8")
    upload_updates = script.split("function updateFbuUploadJobMaterials", 1)[1].split(
        "function waitForFbuUploadPoll", 1
    )[0]
    calculation_poll = script.split("async function pollFbuCalculationJob", 1)[1].split(
        "async function resumeFbuCalculationJob", 1
    )[0]

    assert "function hasFbuJobUiStateChanged" in script
    assert "hasFbuJobUiStateChanged(currentState, candidate)" in upload_updates
    assert "if (changed && state.currentPage === 'workbench')" in upload_updates
    assert "hasFbuJobUiStateChanged(state.calculationJobStatus, job)" in calculation_poll
    assert "await waitForFbuUploadPoll(1500)" in calculation_poll
