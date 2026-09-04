from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "bonus_platform" / "static"


def test_admin_directory_uses_current_brand_and_org_people_layout():
    html = (STATIC / "admin.html").read_text(encoding="utf-8")
    js = (STATIC / "admin.js").read_text(encoding="utf-8")

    assert 'src="assets/workbench-logo-2026.png"' in html
    assert "HRAS 全球薪酬核算工作台" in html
    assert 'id="adminDepartmentTree"' in html
    assert 'id="adminDirectorySync"' in html
    assert "同步飞书通讯录" in html
    assert "工号" in js
    assert "主部门" in js
    assert "飞书用户 ID" in js
    assert "入职日期" not in html + js
    assert "直属主管" not in html + js
    assert "岗位" not in html + js
    assert "员工类型" not in html + js
    assert "工作地点" not in html + js


def test_admin_directory_ui_searches_identity_and_department_fields():
    js = (STATIC / "admin.js").read_text(encoding="utf-8")

    assert "user.employeeNumber" in js
    assert "user.feishuUserId" in js
    assert "user.departmentNames" in js
    assert "state.directory?.canSync" in js
    assert 'fetch("/api/admin/directory/sync"' in js
