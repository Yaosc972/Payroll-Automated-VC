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


def test_upload_job_polling_runs_while_server_request_stays_open():
    script = FBU_JS.read_text(encoding="utf-8")
    upload_area = script.split("async function uploadWorkbenchFilesDirect", 1)[1].split(
        "async function uploadWorkbenchAttendanceFilesDirect", 1
    )[0]
    resume_area = script.split("async function resumeFbuUploadJob", 1)[1].split(
        "function restoreFbuUploadJobs", 1
    )[0]

    assert "const startRequest = apiJson" in upload_area
    assert "const pollingRequest = pollFbuUploadJob(jobId);" in upload_area
    assert upload_area.index("const pollingRequest") < upload_area.index("await startRequest")
    assert "const resumeRequest = apiJson" in resume_area
    assert "const pollingRequest = pollFbuUploadJob(jobId);" in resume_area
    assert resume_area.index("const pollingRequest") < resume_area.index("await resumeRequest")

    calculation_resume = script.split("async function resumeFbuCalculationJob", 1)[1].split(
        "function restoreFbuCalculationJob", 1
    )[0]
    assert "const resumeRequest = apiJson" in calculation_resume
    assert "const pollingRequest = pollFbuCalculationJob(metadata.jobId);" in calculation_resume
    assert calculation_resume.index("const pollingRequest") < calculation_resume.index(
        "await resumeRequest"
    )


def test_upload_start_response_finishes_ui_without_waiting_for_stale_polling():
    script = FBU_JS.read_text(encoding="utf-8")
    completion_area = script.split("async function completeFbuUploadJob", 1)[1].split(
        "async function pollFbuUploadJob", 1
    )[0]
    upload_area = script.split("async function uploadWorkbenchFilesDirect", 1)[1].split(
        "async function uploadWorkbenchAttendanceFilesDirect", 1
    )[0]
    resume_area = script.split("async function resumeFbuUploadJob", 1)[1].split(
        "function restoreFbuUploadJobs", 1
    )[0]

    assert "if (!state.activeFbuUploadJobs[metadata.jobId]) return job;" in completion_area
    assert "const started = await startRequest;" in upload_area
    assert "if (started.job?.status === 'completed')" in upload_area
    assert "return completeFbuUploadJob(metadata, started.job);" in upload_area
    assert "const directUploadStartedAt = performance.now();" in upload_area
    assert "body: JSON.stringify({ clientUploadMs })" in upload_area
    assert "const resumed = await resumeRequest;" in resume_area
    assert "if (resumed.job?.status === 'completed')" in resume_area
    assert "return completeFbuUploadJob(metadata, resumed.job);" in resume_area


def test_upload_completion_merges_authoritative_core_before_rendering_success():
    script = FBU_JS.read_text(encoding="utf-8")
    completion_area = script.split("async function completeFbuUploadJob", 1)[1].split(
        "async function pollFbuUploadJob", 1
    )[0]

    assert "const coreUpdates = job.result?.coreUpdates" in completion_area
    assert "mergeCurrentActivityPayload" in completion_area
    assert completion_area.index("mergeCurrentActivityPayload") < completion_area.index(
        "status: 'done'"
    )
    assert completion_area.count("mergeCurrentActivityPayload") >= 2


def test_calculation_response_finishes_ui_without_waiting_for_stale_polling():
    script = FBU_JS.read_text(encoding="utf-8")
    completion_area = script.split("async function completeFbuCalculationJob", 1)[1].split(
        "async function pollFbuCalculationJob", 1
    )[0]
    resume_area = script.split("async function resumeFbuCalculationJob", 1)[1].split(
        "function restoreFbuCalculationJob", 1
    )[0]
    calculate_area = script.split("async function executeCalculate", 1)[1].split(
        "el.btnCalculate", 1
    )[0]

    assert "if (state.activeCalculationJob?.jobId !== metadata.jobId) return job;" in completion_area
    assert "const resumed = await resumeRequest;" in resume_area
    assert "if (resumed.job?.status === 'completed')" in resume_area
    assert "return completeFbuCalculationJob(metadata, resumed.job);" in resume_area
    assert "if (data.job?.status === 'completed')" in calculate_area
    assert "return completeFbuCalculationJob(state.activeCalculationJob, data.job);" in calculate_area
