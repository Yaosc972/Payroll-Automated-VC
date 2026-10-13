"""Exercise the directory's real JS with synthetic organizational data."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_directory_hierarchy_counts_filters_and_search_are_consistent():
    if not shutil.which("node"):
        pytest.skip("Node is required for directory behavior checks")
    harness = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const elements = new Map();
const document = {
  getElementById(id) {
    if (!elements.has(id)) elements.set(id, { innerHTML: '', addEventListener() {} });
    return elements.get(id);
  },
  addEventListener() {},
};
const window = { location: { search: '' }, addEventListener() {} };
const context = vm.createContext({ document, window, localStorage: { getItem: () => null }, URLSearchParams, structuredClone });
let source = fs.readFileSync(process.argv[1], 'utf8');
source = source.replace(/  render\(\);\n  loadApiState\(\);\n\}\)\(\);\s*$/, `
  window.directoryTest = {
    setState(value) { state = {...state, ...value}; },
    userListUi, departmentUi, filteredUsers, renderDepartmentTree, departmentPath
  };
})();`);
vm.runInContext(source, context);
const t = window.directoryTest;
const departments = [
  { id: 'r', name: '人力中心', parentId: '0' },
  { id: 'a', name: '薪酬部', parentId: 'r' },
  { id: 'b', name: '华南组', parentId: 'a' },
  { id: 'o', name: '招聘部', parentId: 'missing' },
  { id: 'c1', name: '异常甲', parentId: 'c2' },
  { id: 'c2', name: '异常乙', parentId: 'c1' },
  { id: 's', name: '<script>危险组织</script>', parentId: 's' },
];
const users = [
  { id: 'u1', name: '甲', employeeNumber: '1001', directoryScope: 'hras', status: 'active', roleIds: [], departments: [{id:'a'}, {id:'b'}] },
  { id: 'u2', name: '乙', employeeNumber: '1002', directoryScope: 'hras', status: 'pending', roleIds: [], departments: [{id:'b'}] },
  { id: 'u3', name: '丙', directoryScope: 'hras', status: 'active', roleIds: [], departments: [{id:'o'}] },
  { id: 'external', name: '外部人员', directoryScope: 'external', status: 'active', roleIds: [], departments: [] },
];
t.setState({ departments, users });
t.renderDepartmentTree();
const markup = () => document.getElementById('adminDepartmentTree').innerHTML;
const count = id => Number(markup().match(new RegExp('data-department-id="'+id+'"[^>]*>[\\s\\S]*?<b>(\\d+)</b>'))[1]);
assert.equal(count('r'), 2, 'multi-department membership must not double count');
assert.equal(count('a'), 2);
assert.equal(count('b'), 2);
for (const {id} of departments) assert.equal((markup().match(new RegExp('data-department-id="'+id+'"','g')) || []).length, 1, 'each node appears once even with cycles');
assert.ok(markup().includes('&lt;script&gt;危险组织&lt;/script&gt;'));
assert.ok(!markup().includes('<script>'));
assert.ok(markup().includes('admin-tree-children'));
assert.equal(t.departmentPath('b'), '人力中心 / 薪酬部 / 华南组');
assert.ok(t.departmentPath('c1').length < 30, 'cycle paths terminate');
t.userListUi.departmentId = 'a';
assert.equal(t.filteredUsers().length, 2);
t.userListUi.includeDescendants = false;
assert.equal(t.filteredUsers().length, 1);
t.userListUi.includeDescendants = true;
t.userListUi.status = 'pending';
assert.equal(t.filteredUsers()[0].id, 'u2');
t.userListUi.status = 'all';
t.userListUi.query = '1001';
assert.equal(t.filteredUsers()[0].id, 'u1');
t.userListUi.query = '';
t.userListUi.departmentId = 'external';
assert.equal(t.filteredUsers()[0].id, 'external');
t.departmentUi.query = '华南';
t.renderDepartmentTree();
assert.equal((markup().match(/class="admin-tree-node"/g)||[]).length, 3, 'search keeps matching node and ancestors only');
assert.ok(!markup().includes('data-department-id="o"'));
t.departmentUi.query = '不存在';
t.renderDepartmentTree();
assert.ok(markup().includes('没有匹配的组织'));
console.log(JSON.stringify({passed:true}));
'''
    result = subprocess.run(
        ["node", "-e", harness, str(ROOT / "bonus_platform/static/admin.js")],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == {"passed": True}
