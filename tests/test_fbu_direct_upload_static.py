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
