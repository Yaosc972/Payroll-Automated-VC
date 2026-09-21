# -*- coding: utf-8 -*-
from __future__ import annotations

"""
PESEL 提取工具 — 本地网页版
双击运行，浏览器中操作：拖拽上传 PDF → 自动提取 PESEL → 导出 Excel
"""

import os
import re
import sys
import io
import webbrowser
import tempfile
from datetime import datetime
from threading import Timer

from flask import Flask, request, jsonify, send_file, render_template_string
import pdfplumber
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB

# 存储处理结果 (session级别简单存储)
results_store: list[dict] = []

# ============================================================
# PESEL 提取逻辑 (与之前一致)
# ============================================================

def fix_ocr_digits(s: str) -> str:
    ocr_map = {
        'O': '0', 'o': '0', 'I': '1', 'l': '1',
        'S': '5', 's': '5', 'B': '8', 'b': '6',
        'Z': '2', 'z': '2', 'G': '6', 'g': '9',
        'D': '0', 'Q': '0', 'T': '7',
    }
    return ''.join(ocr_map.get(c, c) for c in s)


def validate_pesel(pesel: str) -> bool:
    if len(pesel) != 11 or not pesel.isdigit():
        return False
    weights = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3, 1]
    total = sum(int(pesel[i]) * weights[i] for i in range(11))
    return total % 10 == 0


def extract_pesel_from_text(text: str) -> str | None:
    if not text:
        return None

    # 策略1: PESEL 标签
    for pattern in [r'PESEL[:\s]*([0-9]{11})', r'PESEL[:\s]*([0-9OoIlSsB]{11})']:
        for match in re.findall(pattern, text, re.IGNORECASE):
            fixed = fix_ocr_digits(match)
            if validate_pesel(fixed):
                return fixed

    # 策略2: Nr/Number 标签
    for pattern in [r'(?:Nr|Number|No|Numer)[:\.\s#]*([0-9]{11})',
                    r'(?:Nr|Number|No|Numer)[:\.\s#]*([0-9OoIlSsB]{11})']:
        for match in re.findall(pattern, text, re.IGNORECASE):
            fixed = fix_ocr_digits(match)
            if validate_pesel(fixed):
                return fixed

    # 策略3: 通用11位数字
    for digit_seq in re.findall(r'\b[0-9]{11}\b', text):
        if validate_pesel(digit_seq):
            return digit_seq

    # 策略4: OCR模糊
    for digit_seq in re.findall(r'[0-9OoIlSsBZzGg]{11}', text):
        fixed = fix_ocr_digits(digit_seq)
        if len(fixed) == 11 and fixed.isdigit() and validate_pesel(fixed):
            return fixed

    return None


def extract_text_from_pdf(file_stream) -> str:
    text_parts = []
    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n".join(text_parts)


# ============================================================
# 路由
# ============================================================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/upload', methods=['POST'])
def upload():
    global results_store

    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': '没有上传文件'}), 400

    new_results = []
    for f in files:
        if not f.filename.lower().endswith('.pdf'):
            continue

        filename = f.filename
        try:
            file_stream = io.BytesIO(f.read())
            text = extract_text_from_pdf(file_stream)
            pesel = extract_pesel_from_text(text)

            result = {
                'filename': filename,
                'pesel': pesel or '未找到',
                'status': 'success' if pesel else 'not_found',
            }
        except Exception as e:
            result = {
                'filename': filename,
                'pesel': '—',
                'status': 'error',
                'error': str(e),
            }

        new_results.append(result)

    results_store.extend(new_results)
    return jsonify({'results': new_results, 'total': len(results_store)})


@app.route('/results')
def get_results():
    return jsonify({'results': results_store, 'total': len(results_store)})


@app.route('/clear', methods=['POST'])
def clear():
    global results_store
    results_store = []
    return jsonify({'ok': True})


@app.route('/remove', methods=['POST'])
def remove():
    global results_store
    data = request.get_json()
    idx = data.get('index')
    if idx is not None and 0 <= idx < len(results_store):
        results_store.pop(idx)
    return jsonify({'ok': True, 'total': len(results_store)})


@app.route('/export')
def export_excel():
    if not results_store:
        return jsonify({'error': '没有可导出的数据'}), 400

    wb = Workbook()
    ws = wb.active
    ws.title = "PESEL 提取结果"

    headers = ["序号", "PDF 文件名", "PESEL 号码", "状态"]
    header_font = Font(name="Microsoft YaHei UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4A6CF7", end_color="4A6CF7", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="dcdfe6"),
        right=Side(style="thin", color="dcdfe6"),
        top=Side(style="thin", color="dcdfe6"),
        bottom=Side(style="thin", color="dcdfe6"),
    )

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    data_font = Font(name="Microsoft YaHei UI", size=10)
    success_fill = PatternFill(start_color="EAFaf1", end_color="EAFaf1", fill_type="solid")
    error_fill = PatternFill(start_color="FDEdec", end_color="FDEdec", fill_type="solid")

    for i, r in enumerate(results_store, 2):
        row_data = [i - 1, r['filename'], r['pesel'],
                    '成功' if r['status'] == 'success' else ('未找到' if r['status'] == 'not_found' else '错误')]
        for col, value in enumerate(row_data, 1):
            cell = ws.cell(row=i, column=col, value=value)
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="left" if col != 1 else "center", vertical="center")
            cell.fill = success_fill if r['status'] == 'success' else error_fill

    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 48
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 12
    ws.freeze_panes = "A2"

    # 统计行
    sr = len(results_store) + 3
    success_cnt = sum(1 for r in results_store if r['status'] == 'success')
    ws.cell(row=sr, column=1, value="统计:").font = Font(name="Microsoft YaHei UI", size=10, bold=True)
    ws.cell(row=sr, column=2,
            value=f"共 {len(results_store)} 个 | 成功 {success_cnt} | 失败 {len(results_store) - success_cnt}"
            ).font = Font(name="Microsoft YaHei UI", size=10)
    ws.cell(row=sr + 1, column=1, value="导出时间:").font = Font(name="Microsoft YaHei UI", size=10, bold=True)
    ws.cell(row=sr + 1, column=2, value=datetime.now().strftime("%Y-%m-%d %H:%M:%S")).font = Font(name="Microsoft YaHei UI", size=10)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"PESEL_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename,
    )


# ============================================================
# HTML 模板
# ============================================================

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PESEL 提取工具</title>
<style>
  :root {
    --bg: #f5f6fa;
    --card: #ffffff;
    --primary: #4a6cf7;
    --primary-hover: #3b5de7;
    --text: #2c3e50;
    --text-secondary: #7f8c8d;
    --success: #27ae60;
    --error: #e74c3c;
    --warning: #e67e22;
    --success-bg: #eafaf1;
    --error-bg: #fdedec;
    --border: #dcdfe6;
    --drag-bg: #eef1ff;
    --drag-border: #4a6cf7;
    --radius: 12px;
    --shadow: 0 2px 12px rgba(0,0,0,0.06);
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: "Microsoft YaHei UI", "PingFang SC", "Helvetica Neue", sans-serif;
    background: var(--bg);
    color: var(--text);
    display: flex;
    justify-content: center;
    padding: 40px 20px;
    min-height: 100vh;
  }
  .container {
    width: 100%;
    max-width: 880px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  /* 标题 */
  .header { text-align: center; }
  .header h1 {
    font-size: 26px;
    font-weight: 700;
    color: var(--text);
    margin-bottom: 4px;
  }
  .header p {
    font-size: 14px;
    color: var(--text-secondary);
  }

  /* 上传区域 */
  .dropzone {
    background: var(--card);
    border: 2px dashed var(--border);
    border-radius: var(--radius);
    padding: 48px 24px;
    text-align: center;
    cursor: pointer;
    transition: all 0.25s;
    box-shadow: var(--shadow);
  }
  .dropzone:hover, .dropzone.dragover {
    border-color: var(--drag-border);
    background: var(--drag-bg);
  }
  .dropzone .icon {
    font-size: 48px;
    margin-bottom: 12px;
    display: block;
  }
  .dropzone .main-text {
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 6px;
  }
  .dropzone .sub-text {
    font-size: 13px;
    color: var(--text-secondary);
  }
  .dropzone input { display: none; }

  /* 按钮 */
  .btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 10px 20px;
    border: none;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s;
    font-family: inherit;
  }
  .btn-primary {
    background: var(--primary);
    color: #fff;
  }
  .btn-primary:hover {
    background: var(--primary-hover);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(74,108,247,0.35);
  }
  .btn-outline {
    background: #fff;
    color: var(--text);
    border: 1.5px solid var(--border);
  }
  .btn-outline:hover {
    border-color: var(--primary);
    color: var(--primary);
  }
  .btn-danger {
    background: #fff;
    color: var(--error);
    border: 1.5px solid var(--error);
  }
  .btn-danger:hover {
    background: var(--error);
    color: #fff;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
  }

  .actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
  }
  .actions .right { margin-left: auto; display: flex; gap: 10px; }

  /* 表格 */
  .table-card {
    background: var(--card);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    overflow: hidden;
  }
  .table-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
  }
  .table-header .title {
    font-weight: 600;
    font-size: 15px;
  }
  .table-header .count {
    font-size: 13px;
    color: var(--text-secondary);
  }
  table {
    width: 100%;
    border-collapse: collapse;
  }
  thead th {
    text-align: left;
    padding: 10px 20px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    border-bottom: 2px solid var(--border);
    background: #fafbfc;
  }
  tbody td {
    padding: 10px 20px;
    font-size: 14px;
    border-bottom: 1px solid #f0f1f5;
  }
  tbody tr:hover { background: #f8f9fb; }
  tbody tr.success { background: var(--success-bg); }
  tbody tr.error { background: var(--error-bg); }
  tbody tr.success:hover { background: #dff0e5; }
  tbody tr.error:hover { background: #f9e2e0; }

  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
  }
  .badge-success { background: #d5f5e3; color: #1e8449; }
  .badge-error { background: #fadbd8; color: #c0392b; }
  .badge-notfound { background: #fdebd0; color: #b9770e; }

  .pesel-num {
    font-family: "Consolas", "Courier New", monospace;
    font-size: 13px;
    letter-spacing: 1px;
  }
  .pesel-num.missing { color: #ccc; }

  .delete-btn {
    background: none;
    border: none;
    cursor: pointer;
    color: #ccc;
    font-size: 18px;
    padding: 0 4px;
    transition: color 0.2s;
  }
  .delete-btn:hover { color: var(--error); }

  /* 统计栏 */
  .stats {
    display: flex;
    gap: 20px;
    padding: 14px 20px;
    background: #fafbfc;
    border-top: 1px solid var(--border);
    font-size: 13px;
    color: var(--text-secondary);
  }
  .stats strong { color: var(--text); }

  /* 空状态 */
  .empty {
    padding: 60px 20px;
    text-align: center;
    color: var(--text-secondary);
  }
  .empty .icon { font-size: 48px; margin-bottom: 10px; display: block; }

  /* 加载动画 */
  .spinner {
    display: inline-block;
    width: 16px; height: 16px;
    border: 2px solid #fff;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .toast {
    position: fixed; top: 20px; right: 20px;
    padding: 12px 20px;
    border-radius: 8px;
    color: #fff;
    font-size: 14px;
    opacity: 0;
    transform: translateY(-10px);
    transition: all 0.3s;
    z-index: 999;
    pointer-events: none;
  }
  .toast.show { opacity: 1; transform: translateY(0); }
  .toast-success { background: var(--success); }
  .toast-error { background: var(--error); }
</style>
</head>
<body>

<div class="container">
  <div class="header">
    <h1>PESEL 提取工具</h1>
    <p>上传 PDF 文件，自动提取 PESEL 号码并导出为 Excel</p>
  </div>

  <!-- 上传区域 -->
  <div class="dropzone" id="dropzone">
    <span class="icon">📄</span>
    <div class="main-text">拖拽 PDF 文件到此处</div>
    <div class="sub-text">或点击选择文件（支持多选）</div>
    <input type="file" id="fileInput" accept=".pdf" multiple>
  </div>

  <!-- 操作按钮 -->
  <div class="actions">
    <button class="btn btn-outline" id="btnSelect" onclick="document.getElementById('fileInput').click()">
      选择 PDF 文件
    </button>
    <span class="right">
      <button class="btn btn-danger" id="btnClear" onclick="clearAll()" disabled>清空列表</button>
      <button class="btn btn-primary" id="btnExport" onclick="exportExcel()" disabled>导出 Excel</button>
    </span>
  </div>

  <!-- 结果表格 -->
  <div class="table-card" id="tableCard" style="display:none">
    <div class="table-header">
      <span class="title">提取结果</span>
      <span class="count" id="tableCount">0 个文件</span>
    </div>
    <table>
      <thead>
        <tr>
          <th style="width:50px">#</th>
          <th>PDF 文件名</th>
          <th style="width:170px">PESEL 号码</th>
          <th style="width:80px">状态</th>
          <th style="width:40px"></th>
        </tr>
      </thead>
      <tbody id="resultBody"></tbody>
    </table>
    <div class="stats" id="statsBar" style="display:none">
      <span>共 <strong id="statTotal">0</strong> 个</span>
      <span>成功 <strong id="statSuccess" style="color:var(--success)">0</strong></span>
      <span>失败 <strong id="statFail" style="color:var(--error)">0</strong></span>
    </div>
  </div>

  <!-- 空状态 -->
  <div class="table-card" id="emptyState">
    <div class="empty">
      <span class="icon">📋</span>
      <p>暂无数据，请上传 PDF 文件</p>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const resultBody = document.getElementById('resultBody');
const tableCard = document.getElementById('tableCard');
const emptyState = document.getElementById('emptyState');
const btnClear = document.getElementById('btnClear');
const btnExport = document.getElementById('btnExport');
const statsBar = document.getElementById('statsBar');

let allResults = [];

// 拖拽事件
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('dragover'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('dragover');
  const files = Array.from(e.dataTransfer.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
  if (files.length) uploadFiles(files);
  else toast('请拖入 .pdf 文件', 'error');
});
dropzone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
  const files = Array.from(fileInput.files);
  if (files.length) uploadFiles(files);
  fileInput.value = '';
});

async function uploadFiles(files) {
  btnExport.disabled = true;
  btnClear.disabled = true;

  const formData = new FormData();
  files.forEach(f => formData.append('files', f));

  try {
    const resp = await fetch('/upload', { method: 'POST', body: formData });
    const data = await resp.json();
    if (data.results) {
      allResults = allResults.concat(data.results);
      renderTable();
      toast(`成功处理 ${data.results.length} 个文件`);
    }
  } catch (err) {
    toast('上传失败: ' + err.message, 'error');
  }

  btnExport.disabled = allResults.length === 0;
  btnClear.disabled = allResults.length === 0;
}

function renderTable() {
  if (allResults.length === 0) {
    tableCard.style.display = 'none';
    emptyState.style.display = '';
    statsBar.style.display = 'none';
    btnClear.disabled = true;
    btnExport.disabled = true;
    return;
  }

  tableCard.style.display = '';
  emptyState.style.display = 'none';
  document.getElementById('tableCount').textContent = `${allResults.length} 个文件`;

  resultBody.innerHTML = allResults.map((r, i) => {
    const rowClass = r.status === 'success' ? 'success' : 'error';
    let badgeHtml, peselHtml;
    if (r.status === 'success') {
      badgeHtml = '<span class="badge badge-success">成功</span>';
      peselHtml = `<span class="pesel-num">${r.pesel}</span>`;
    } else if (r.status === 'not_found') {
      badgeHtml = '<span class="badge badge-notfound">未找到</span>';
      peselHtml = '<span class="pesel-num missing">未找到</span>';
    } else {
      badgeHtml = '<span class="badge badge-error">错误</span>';
      peselHtml = `<span class="pesel-num missing" title="${r.error || ''}">—</span>`;
    }
    return `<tr class="${rowClass}">
      <td>${i + 1}</td>
      <td>${escHtml(r.filename)}</td>
      <td>${peselHtml}</td>
      <td>${badgeHtml}</td>
      <td><button class="delete-btn" onclick="removeItem(${i})" title="删除此行">×</button></td>
    </tr>`;
  }).join('');

  // 统计
  const success = allResults.filter(r => r.status === 'success').length;
  const fail = allResults.length - success;
  document.getElementById('statTotal').textContent = allResults.length;
  document.getElementById('statSuccess').textContent = success;
  document.getElementById('statFail').textContent = fail;
  statsBar.style.display = '';

  btnClear.disabled = false;
  btnExport.disabled = false;
}

async function removeItem(index) {
  allResults.splice(index, 1);
  renderTable();
  await fetch('/remove', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({index})
  });
}

async function clearAll() {
  if (!confirm('确定要清空所有结果吗？')) return;
  allResults = [];
  renderTable();
  await fetch('/clear', { method: 'POST' });
}

function exportExcel() {
  window.location.href = '/export';
}

function toast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast toast-${type} show`;
  setTimeout(() => el.classList.remove('show'), 2500);
}

function escHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

// 初始加载已有结果
fetch('/results').then(r => r.json()).then(data => {
  if (data.results && data.results.length) {
    allResults = data.results;
    renderTable();
  }
});
</script>
</body>
</html>
'''


# ============================================================
# 启动
# ============================================================

def open_browser():
    webbrowser.open('http://127.0.0.1:58888')


if __name__ == '__main__':
    print("=" * 50)
    print("  PESEL 提取工具")
    print("  服务地址: http://127.0.0.1:58888")
    print("  浏览器将自动打开，如未打开请手动访问")
    print("  按 Ctrl+C 停止服务")
    print("=" * 50)
    Timer(1.0, open_browser).start()
    app.run(host='127.0.0.1', port=58888, debug=False)
