#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
办公工具集成平台 (网页版, 本地服务 / 飞书企业登录)
-----------------------------------------------------------------------
双击 run_web.bat 启动后, 浏览器自动打开平台首页: 左侧导航 + 顶部搜索/用户 +
中间工具卡片网格。点卡片进入该工具的运行页 (拖文件 -> 处理 -> 下载), 全部本地处理。
后端复用 swedish_tax_pdf_extractor 的已验证提取逻辑 (29 人已跑通)。

平台采用「路由 + 工具注册表」结构:
  - TOOLS 是全局注册表, 每个工具 = {id, name, desc, accept, process, enabled,
    en_name, version, status_text, last_batch, last_result, category, ...}
  - 前端首页从 /api/tools 拉列表自动渲染卡片
  - 新增一个工具 = 写一个 process 函数 + 加一行 register_tool(...) , 不动主框架

飞书登录 (OAuth 2.0 授权码模式, 标准流程):
  - GET  /login/feishu   生成一次性 state -> 写 oauth_state(HttpOnly) Cookie ->
                         302 到飞书授权页 (带 app_id / redirect_uri / state)
  - GET  /feishu/callback 飞书带着 code+state 跳回; 先校验 state == cookie 中的 state,
                         再服务端用 app_id+app_secret 换 access_token (secret 不出服务端),
                         再取 userinfo (open_id / name / tenant_key), 写 session, 重定向 /
  - GET  /api/me         返回当前登录用户 (或 null)
  - GET  /logout         清除 session
  - GET  /api/tools      返回已注册工具列表 (首页卡片用)
  - POST /api/tool/<id>/process  需有效 session, 调用对应工具的 process 处理文件

tenant_key: 首次真实登录成功后自动回填到本地 feishu_config.json, 不预先编造。

部署/配置: 见同目录 feishu_config.json (本地配置, 不入库)。
环境覆盖 (可选): WEB_PORT / WEB_HOST / FEISHU_CONFIG / FEISHU_MOCKED
"""

import base64
import json
import os
import sys
import secrets
import shutil
import socket
import re
import yaml
import tempfile
import time
import io
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

# 惰性加载：服务器启动时不导入 fitz/pdfplumber 等重依赖，首次使用 PDF 工具时才加载，降低常驻内存
ext = pen = hum = npr = ita = dpa = None
paie = None

def _ensure_modules():
    """首次使用 PDF/import 工具时再导入重依赖模块（fitz/pdfplumber/openpyxl 等）。"""
    global ext, pen, hum, npr, ita, dpa, paie
    if ext is not None:
        return
    import swedish_tax_pdf_extractor as ext
    import pension_pdf_to_excel as pen
    import humana_details_extract as hum
    import norway_pdf_parser as npr
    import italy_payslip_parser as ita
    import dutch_payslip_parser as dpa
    # 法国 Payfit import 自动填写（复用 import-paie-autofill 技能脚本，单一数据源）
    try:
        import sys as _sys
        # 可移植查找顺序：
        #   1) 环境变量 PAIE_SKILL_SCRIPTS（部署时最灵活）
        #   2) 随包同目录 import-paie-autofill/scripts（发给同事/换机器用）
        #   3) 本机 WorkBuddy 技能目录（原开发环境）
        _cands = []
        if os.environ.get("PAIE_SKILL_SCRIPTS", ""):
            _cands.append(os.environ["PAIE_SKILL_SCRIPTS"])
        _cands.append(os.path.join(_BASE, "import-paie-autofill", "scripts"))
        _cands.append(r"C:\Users\Administrator\.workbuddy\skills\import-paie-autofill\scripts")
        _loaded = False
        for _p in _cands:
            if not os.path.isdir(_p):
                continue
            if _p not in _sys.path:
                _sys.path.insert(0, _p)
            try:
                import auto_fill_import as paie
                _loaded = True
                break
            except Exception:
                try:
                    _sys.path.remove(_p)
                except Exception:
                    pass
                paie = None
        if not _loaded:
            raise ImportError("未找到 auto_fill_import，已尝试: %s" % _cands)
    except Exception as _e:
        paie = None
        print("[WARN] 法国 import 自动填写模块未能加载:", _e)


# ---------------------------------------------------------------------------
# 运行参数 / 本地配置
# ---------------------------------------------------------------------------
PORT = int(os.environ.get("WEB_PORT", "8765"))
HOST = os.environ.get("WEB_HOST", "0.0.0.0")
PORT_SPAN = 10                      # 端口占用时在 PORT ~ PORT+SPAN 内顺延
SESSION_TTL = 3600 * 8              # session 有效期 8 小时

_BASE = os.path.dirname(os.path.abspath(__file__))
# 可写状态文件（配置/口令/已知用户）落地到 exe 同级目录，保证打包后修改可持久化；
# 数据只读文件（import_templates、norway_supplier.yaml）仍用 _BASE（PyInstaller 临时解压目录）。
if getattr(sys, "frozen", False):
    _EXE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    _EXE_DIR = _BASE

# 关键修复(20260819): PyInstaller console EXE 在无控制台环境(后台任务/计划任务)启动时,
# print 到无效句柄会抛 OSError [Errno 22] Invalid argument, 导致解析器内打印日志时整个工具崩溃
# (意大利工资单逐条打印 900+ 行必触发, 挪威/瑞典次之)。打包态统一把 stdout/stderr 重定向到
# exe 同级 web_server.log(行缓冲 + utf-8 + errors=replace), 任何启动方式都不再崩, 顺带留日志。
if getattr(sys, "frozen", False):
    try:
        _logf = open(os.path.join(_EXE_DIR, "web_server.log"), "a", encoding="utf-8", errors="replace", buffering=1)
        sys.stdout = _logf
        sys.stderr = _logf
    except Exception:
        pass

CONFIG_PATH = os.environ.get("FEISHU_CONFIG", os.path.join(_EXE_DIR, "feishu_config.json"))
FEISHU_ENABLED = False  # 已统一关闭飞书登录，仅保留共享口令模式
DISABLED_FILE = os.path.join(_EXE_DIR, "disabled_users.json")   # 停用的 open_id 列表
KNOWN_FILE = os.path.join(_EXE_DIR, "known_users.json")         # 已登录过的 open_id 集合
PASSCODE_FILE = os.path.join(_EXE_DIR, "share_passcode.txt")     # 共享口令持久化文件（可在网页内修改）

def _safe_filename(filename, default="input.pdf"):
    """把上传文件名整理成 Windows/跨平台安全的路径名：去掉控制字符、保留字符、首尾空格。"""
    if not filename:
        return default
    name = os.path.basename(filename)
    # 1) 替换 Windows 保留字符
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    # 2) 替换所有 ASCII 控制字符（\x00-\x1f 以及 \x7f）
    name = re.sub(r'[\x00-\x1f\x7f]', "_", name)
    # 3) 去掉首尾空白（含 \x20 和各类 Unicode 空白）
    name = name.strip()
    if not name:
        return default
    # 4) 避免 Windows 保留设备名（如 CON, PRN, AUX, NUL, COM1..COM9, LPT1..LPT9）
    base_no_ext = os.path.splitext(name)[0].upper()
    if base_no_ext in {"CON", "PRN", "AUX", "NUL"} or re.match(r"^(COM|LPT)[1-9]$", base_no_ext):
        ext = os.path.splitext(name)[1]
        name = f"{base_no_ext}_file{ext}"
    return name
SHARE_PASSCODE = os.environ.get("SHARE_PASSCODE", "")         # 非空则开启「共享口令」模式（轻量免登录网关）
if not SHARE_PASSCODE and os.path.exists(PASSCODE_FILE):
    try:
        with open(PASSCODE_FILE, encoding="utf-8") as _f:
            SHARE_PASSCODE = _f.read().strip()
    except Exception:
        SHARE_PASSCODE = ""
# 打包成单文件 EXE 后，若 exe 同级目录没有 share_passcode.txt，则回退到打包内置的默认值
#（保证只发一个 exe 给同事也能用默认口令）
if not SHARE_PASSCODE and getattr(sys, "frozen", False):
    _builtin_passcode = os.path.join(_BASE, "share_passcode.txt")
    if os.path.exists(_builtin_passcode):
        try:
            with open(_builtin_passcode, encoding="utf-8") as _f:
                SHARE_PASSCODE = _f.read().strip()
        except Exception:
            SHARE_PASSCODE = ""

# 仅在「仍为打包内置默认口令」时，在登录页展示口令提示，方便同事首次进入；
# 一旦用户通过网页修改过口令（写入 PASSCODE_FILE），则不再展示。
_BUILTIN_PASSCODE = ""
try:
    with open(os.path.join(_BASE, "share_passcode.txt"), encoding="utf-8") as _f:
        _BUILTIN_PASSCODE = _f.read().strip()
except Exception:
    _BUILTIN_PASSCODE = ""
if SHARE_PASSCODE and SHARE_PASSCODE == _BUILTIN_PASSCODE:
    _PASSCODE_HINT_HTML = "共享口令（默认）：<b>%s</b>　进入后可在右上角「修改口令」更改" % SHARE_PASSCODE
else:
    _PASSCODE_HINT_HTML = ""

# 免登录模式：开启后无需任何口令/登录即可使用全部工具（适用于内网可信环境）。
# 如需恢复「共享口令」，设置环境变量 NO_AUTH=0 即可。
NO_AUTH = os.environ.get("NO_AUTH", "1").lower() in ("1", "true", "yes")

DEFAULT_CONFIG = {
    "app_id": "",
    "app_secret": "",
    "redirect_uri": "http://localhost:8765/feishu/callback",
    "authorize_url": "https://open.feishu.cn/open-apis/authen/v1/authorize",
    "token_url": "https://open.feishu.cn/open-apis/authen/v1/access_token",
    "userinfo_url": "https://open.feishu.cn/open-apis/authen/v1/user_info",
    "feishu_mocked": False,
    "session_secret": "",
    "tenant_key": "",
}


def load_config():
    if not FEISHU_ENABLED:
        # 飞书登录已关闭：仅保留内存默认配置，不再读取/写入 feishu_config.json
        #（避免分发包每次启动又在 exe 同级目录生成该文件）
        cfg = dict(DEFAULT_CONFIG)
        if not cfg.get("session_secret"):
            cfg["session_secret"] = secrets.token_hex(16)
        return cfg
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = dict(DEFAULT_CONFIG)
    changed = False
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
            changed = True
    if os.environ.get("FEISHU_MOCKED", "").lower() in ("1", "true", "yes"):
        cfg["feishu_mocked"] = True
    if not cfg.get("session_secret"):
        cfg["session_secret"] = secrets.token_hex(16)
        changed = True
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


CFG = load_config()


# ---------------------------------------------------------------------------
# 用户态: 内存 session + 停用/已知用户文件
# ---------------------------------------------------------------------------
SESSIONS = {}          # sid -> {open_id, name, tenant_key, first_login, ts}

# OAuth state 服务端兜底存储：跨站/第三方 cookie 被浏览器阻止时，仍可从内存校验。
# key=state, value={ip, ts, redirect_uri}; 5 分钟过期
STATE_STORE = {}
STATE_TTL = 300

# 登录调试日志（排查期默认开启；排查完改回 os.environ.get("WEB_DEBUG_LOG")）
DEBUG_LOG = os.environ.get("WEB_DEBUG_LOG", "1")


def dlog(*args):
    if not DEBUG_LOG:
        return
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "login_debug.log"), "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), " ".join(str(a) for a in args)))
    except Exception:
        pass


def _store_state(state, ip, redirect_uri):
    now = time.time()
    # 清理过期项
    expired = [k for k, v in STATE_STORE.items() if now - v.get("ts", 0) > STATE_TTL]
    for k in expired:
        STATE_STORE.pop(k, None)
    STATE_STORE[state] = {"ip": ip, "ts": now, "redirect_uri": redirect_uri}


def _check_state(state, ip):
    """校验 state 是否由本机近期生成。允许 IP 变化（用户可能在移动网络/WiFi 间切换），
    但要求 state 存在于内存且未过期。"""
    now = time.time()
    rec = STATE_STORE.get(state)
    if not rec:
        return False
    if now - rec.get("ts", 0) > STATE_TTL:
        STATE_STORE.pop(state, None)
        return False
    return True


def load_set(path):
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_set(path, s):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_disabled():
    return load_set(DISABLED_FILE)


def add_disabled(open_id):
    s = load_disabled()
    s.add(open_id)
    save_set(DISABLED_FILE, s)


def load_known():
    return load_set(KNOWN_FILE)


def mark_known(open_id):
    s = load_known()
    s.add(open_id)
    save_set(KNOWN_FILE, s)


# ---------------------------------------------------------------------------
# 工具注册表 (新增工具只需加一个 process 函数 + 一行 register_tool)
# ---------------------------------------------------------------------------
TOOLS = {}


def register_tool(tid, name, desc, process_fn=None, accept="", enabled=True,
                en_name="", version="", status_text="", last_batch="",
                last_result="", btn_text="", category="", process_multi=None,
                preview=False, country=""):
    """注册一个工具到平台。
    tid:        唯一 id (用于路由和前端)
    name:       卡片中文标题
    desc:       卡片描述
    process_fn: 处理函数, 签名 (filename:str, raw:bytes) -> (out_name, out_b64)
                或 (out_name, out_b64, extra_info) ; 返回 None 表示不支持该文件
    accept:     文件选择框接受的后缀, 如 ".pdf" (空=不限制)
    enabled:    False 时卡片显示"无权限进入"且不可用
    en_name:    卡片顶部英文标签
    version:    版本号, 如 "v1.0"
    status_text:状态文字, 如 "稳定主模块" / "试运行" / "已上线"
    last_batch: 最近批次, 如 "2026-05" / "2026-08"
    last_result:最近结果, 如 "29人" / "1191人"
    btn_text:   自定义按钮文字 (空则按 enabled/登录态自动生成)
    category:   左侧导航分组, 如 "海外核算" / "工资核算"
    process_multi: 多文件处理函数, 签名 (payload:dict) -> (out_name, out_b64, extra_info)
                当 POST 体含 {"files":[{filename,data}...]} 时优先调用 (如 import 工具需同时传源表+模板)
    country:    首页国家分组标签, 如 "挪威" / "瑞典" / "荷兰" / "美国" / "中国";
                首页按国家折叠展示, 同一国家下可折叠多个工具 (空=归入"通用")
    """
    TOOLS[tid] = {
        "id": tid, "name": name, "desc": desc,
        "process": process_fn, "accept": accept, "enabled": enabled,
        "en_name": en_name or tid.upper().replace("_", " "),
        "version": version or "v0.1",
        "status_text": status_text or ("已上线" if enabled else "即将上线"),
        "last_batch": last_batch or "-",
        "last_result": last_result or "-",
        "btn_text": btn_text,
        "category": category or "业务模块",
        "process_multi": process_multi,
        "preview": preview,
        "country": country or "通用",
    }


# ---------------------------------------------------------------------------
# 失败智能诊断：扫描件 / 格式不符 自检
# ---------------------------------------------------------------------------
def _pdf_has_text_layer(raw):
    """检测 PDF 是否有文本层。返回 (kind, page_count, has_text)
    kind: 'pdf' | 'not_pdf' | 'parse_error'
    """
    if not raw or raw[:5] != b"%PDF-":
        return ("not_pdf", 0, False)
    try:
        import pdfplumber
        opener = pdfplumber.open
    except Exception:
        try:
            from pypdf import PdfReader
            def _fallback(bio):
                r = PdfReader(bio)
                class _W:
                    pages = r.pages
                    def __enter__(self): return self
                    def __exit__(self, *a): return False
                return _W()
            opener = _fallback
        except Exception:
            return ("parse_error", 0, False)
    try:
        with opener(io.BytesIO(raw)) as pdf:
            n = len(pdf.pages) if hasattr(pdf, "pages") else 0
            has = False
            for p in (pdf.pages or [])[:3]:
                try:
                    t = p.extract_text() or ""
                except Exception:
                    t = ""
                if t.strip():
                    has = True
                    break
            return ("pdf", n, has)
    except Exception:
        return ("parse_error", 0, False)


# 各国工具「期望格式 + 失败自查」速查
TOOL_HINTS = {
    "swedish_tax": "瑞典雇主申报表(Arbetsgivardeklaration)：需含员工抬头行（如 '001 - Name' / 'KU10 - Name' / 'Specifikationsnummer X'）与 Ruta / Namn / Värde 明细。自查：① 是否扫描件图片型？② 抬头行格式是否非常规？③ 是否非瑞典税务表？",
    "dutch_pension": "荷兰养老金账单（如 Zwitserleven）：需为表格型 PDF，含参保人、金额列与账单 Final total。自查：① 是否扫描件？② 是否该机构固定 9 列格式？",
    "dutch_payslip": "荷兰工资单（如 CIRRO Loonstrook）：需含 Salarisspecificatie 分组与 Code/Omschrijving/Waarde/Betaling/Inhouding 等列。自查：① 是否扫描件？② 是否坐标错位的特殊排版？",
    "humana_details": "美国 Humana 医疗账单：需含 'Employee Detail' 区块及员工×计划(DHP/DTP/VIS)×月份明细。自查：① 是否为含该区块的 PDF？② 是否扫描件？",
    "norway_payslip": "挪威工资单(Lønnslip)：需含挪威语关键词（Skatt / Arbeidsgiver / Trekk / Brutto 等）的可识别文本。自查：① 是否扫描件？② 是否挪威语工资单？",
    "norway_payment": "挪威付款清单：需含表头（序号/收款人/KID/账号/SWIFT/Beløp）的表格。自查：① 是否为银行导出 PDF？② 是否扫描件？",
    "italy_payslip": "意大利工资单（Zucchetti Libro Unico）：需含 voci/competenze 科目明细与 Totale Competenze 汇总。自查：① 是否扫描件？② 是否 Zucchetti 坐标表格排版？",
    "import_paie": "法国 Payfit import：需为 .xlsx 且含『出勤情况』+『工资合计』两个 Sheet。自查：① 是否上传了 xlsx 而非 pdf？② 是否包含指定的两个 Sheet？③ 是否用了正确模板？",
}


def _diagnose_failure(tool_id, filename, data, tool_reason=None):
    """工具返回 None（无数据）时，给出智能诊断，减少来回试错。"""
    fn = (filename or "").lower()
    is_pdf = fn.endswith(".pdf") or (data and data[:5] == b"%PDF-")
    is_xlsx = fn.endswith(".xlsx") or (data and data[:2] == b"PK")
    base = tool_reason or "未提取到有效数据，可能为扫描件、格式不符或 PDF 中无可识别表格。"
    lines = [base]
    if is_pdf:
        kind, n, has = _pdf_has_text_layer(data or b"")
        if kind == "not_pdf":
            lines.append("⚠ 文件头不是标准 PDF，请确认上传的是 PDF。")
        elif kind == "parse_error":
            lines.append("⚠ PDF 无法解析（可能加密、损坏或非标准格式）。")
        elif kind == "pdf" and not has:
            lines.append("⚠ 疑似扫描件 / 图片型 PDF：本工具基于文本解析，PDF 内无可提取文本层。请用 OCR 转文字后重试，或导出为文本型 PDF（如从源系统重新导出水印/矢量版）。")
        elif kind == "pdf" and has:
            lines.append("✓ PDF 含文本层，但当前工具未能识别目标结构（格式不符）。")
    elif is_xlsx:
        lines.append("✓ 已识别为 Excel 文件。")
    else:
        lines.append("⚠ 无法判断文件类型（建议上传 PDF 或 XLSX）。")
    hint = TOOL_HINTS.get(tool_id)
    if hint:
        lines.append("【本工具期望格式】" + hint)
    return "\n".join(lines)


# ---- 导出脱敏（统一出口后处理，不改动任何 parser） ----
SENSITIVE_HEADER_KEYWORDS = (
    'tax', 'fiscal', 'codice', 'personnummer', 'personnr', 'ssn',
    'security', 'sécurité', 'securite', 'social', '社保', '税号', '身份证', '税',
    '银行卡', '卡号', '账号', 'iban', 'account', 'rekening', 'kontonr', 'bsn',
    'numéro', 'numero',
)
# 命中上述关键词后，若同时含这些词则排除（避免误伤银行名称、员工姓名/编号等非敏感列）
SENSITIVE_EXCLUDE = ('name', '姓名', '员工', 'employee', '编号')


def _header_is_sensitive(header):
    s = header if isinstance(header, str) else ('' if header is None else str(header))
    s = s.lower()
    if not s:
        return False
    if any(ex in s for ex in SENSITIVE_EXCLUDE):
        return False
    return any(kw in s for kw in SENSITIVE_HEADER_KEYWORDS)


def _mask_value(v):
    """保留前2后4，中间用 * 填充；过短或空值原样返回。"""
    if v is None:
        return v
    s = str(v)
    n = len(s)
    if n < 6:
        return v
    if n < 8:
        return s[0] + '*' * (n - 2) + s[-1]
    return s[:2] + '*' * (n - 6) + s[-4:]


def mask_xlsx(b64):
    """对 xlsx(base64) 中所有敏感表头列做脱敏，返回新的 base64。
    任何异常都回退为原文件，保证不阻断正常导出。"""
    try:
        from io import BytesIO
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(base64.b64decode(b64)))
        changed = False
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            header = rows[0]
            sens_cols = [i for i, h in enumerate(header) if _header_is_sensitive(h)]
            if not sens_cols:
                continue
            for r in range(1, len(rows)):
                row = rows[r]
                for c in sens_cols:
                    if c >= len(row):
                        continue
                    val = row[c]
                    if val is None or (isinstance(val, str) and not val.strip()):
                        continue
                    newv = _mask_value(val)
                    if newv != val:
                        ws.cell(row=r + 1, column=c + 1).value = newv
                        changed = True
        if not changed:
            return b64
        buf = BytesIO()
        wb.save(buf)
        return base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception as e:
        print("[WARN] mask_xlsx 失败，回退原文件:", e)
        return b64


# ---- 台账结构化字段计算（统一出口调用，不改动任何 parser）----
def _parse_money(cell):
    """解析金额单元格为 float，兼容 1.234,56 / 1234.56 / (3,45) / 1 234 等写法。无法解析返回 None。"""
    if cell is None:
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    s = str(cell).strip().replace("\u00a0", "").replace(" ", "")
    if not s:
        return None
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.lstrip("-").strip("()").replace("(", "").replace(")", "")
    if not s:
        return None
    if "," in s and "." in s:
        # 最后一个分隔符为小数位
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        s = s.replace(",", ".") if (len(parts) == 2 and len(parts[1]) <= 2) else s.replace(",", "")
    s = "".join(ch for ch in s if ch.isdigit() or ch == ".")
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _parse_count(info):
    """从工具的 people 文案中提取人数，如 '48名员工' / '1 名员工'。失败返回 None。"""
    if not info:
        return None
    import re as _re
    m = _re.search(r"(\d+)\s*名?\s*员工", str(info))
    if m:
        return int(m.group(1))
    m = _re.search(r"(\d+)\s*人", str(info))
    if m:
        return int(m.group(1))
    m = _re.search(r"(\d+)", str(info))
    if m:
        return int(m.group(1))
    return None


def _parse_month(filename):
    """从文件名提取 20YYMM；提取不到则回退为处理时间当月（YYYY-MM）。"""
    import re as _re
    from datetime import datetime
    m = _re.search(r"20(\d{2})(\d{2})", filename or "")
    if m:
        yy, mm = m.group(1), m.group(2)
        if 1 <= int(mm) <= 12:
            return "20%s-%s" % (yy, mm)
    d = datetime.now()
    return "%04d-%02d" % (d.year, d.month)


def compute_gross_from_xlsx(b64):
    """在输出 xlsx 中寻找应发列（应发/Brutto/Gross/Totale Competenze 等）并求和。
    仅作估算，供台账看板展示；找不到则返回 None。任何异常均回退 None。"""
    try:
        from io import BytesIO
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(base64.b64decode(b64)), data_only=True)
    except Exception:
        return None
    total = 0.0
    found = False
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header_idx = None
        for i, r in enumerate(rows):
            if any(isinstance(c, str) and c.strip() for c in r):
                header_idx = i
                break
        if header_idx is None:
            continue
        headers = [str(c).strip().lower() if c is not None else "" for c in rows[header_idx]]
        gi = None
        for idx, h in enumerate(headers):
            hl = h.lower()
            if any(k in hl for k in ("应发", "brutto", "brut", "gross", "totale competenze",
                                     "competenze", "salario", "salary", "remuneration", "retrib")):
                gi = idx
                break
        if gi is None:
            continue
        for r in rows[header_idx + 1:]:
            if gi >= len(r):
                continue
            rowtext = " ".join(str(x) for x in r if x is not None).lower()
            if "合计" in rowtext or "total" in rowtext or "summa" in rowtext:
                continue  # 跳过合计行，避免重复计入
            v = _parse_money(r[gi])
            if v is not None:
                total += v
                found = True
    return round(total, 2) if found else None


# ---- 工具①：瑞典税务 PDF 提取 (复用现有验证过的逻辑) ----
def process_swedish_tax(filename, raw):
    tmpdir = tempfile.mkdtemp(prefix="swetax_web_")
    try:
        pdf_path = os.path.join(tmpdir, _safe_filename(filename, default="swedish_tax.pdf"))
        with open(pdf_path, "wb") as f:
            f.write(raw)
        records = ext.extract_from_path(pdf_path)
        if not records:
            err = "瑞典工具未识别到员工记录。可能原因：① 抬头行格式不是常见的 '001 - Name' / 'KU10 - Name' / 'Specifikationsnummer X'；② PDF为扫描件图片型；③ 非瑞典税务表格式。"
            print(f"[WARN] {filename}: {err}")
            return (None, None, err)
        xlsx_path = os.path.join(tmpdir, "result.xlsx")
        ext.write_excel(records, xlsx_path)
        with open(xlsx_path, "rb") as f:
            xlsx_b64 = base64.b64encode(f.read()).decode("ascii")
        out_name = os.path.splitext(os.path.basename(filename))[0] + "_result.xlsx"
        return (out_name, xlsx_b64, f"{len(records)} 名员工")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---- 工具④：荷兰养老金 PDF 提取 (复用 pension_pdf_to_excel) ----
def process_dutch_pension(filename, raw):
    tmpdir = tempfile.mkdtemp(prefix="nlpen_web_")
    try:
        pdf_path = os.path.join(tmpdir, _safe_filename(filename, default="pension.pdf"))
        with open(pdf_path, "wb") as f:
            f.write(raw)
        data_rows, candidate_header, verify_info = pen.extract_from_pdf(pdf_path)
        if not data_rows:
            print(f"[WARN] 未从 {filename} 提取到数据行（可能表格未识别/扫描件）")
            return None
        xlsx_path = os.path.join(tmpdir, "result.xlsx")
        pen.write_excel(data_rows, candidate_header, xlsx_path, verify_info)
        with open(xlsx_path, "rb") as f:
            xlsx_b64 = base64.b64encode(f.read()).decode("ascii")
        out_name = os.path.splitext(os.path.basename(filename))[0] + "_pension.xlsx"
        # extra_info: 行数 + 验算结果（区分 通过/差异/无法验算）
        if verify_info:
            n = len(data_rows)
            if not verify_info.get("verified"):
                extra = f"{n}人 ⚠未识别Final total无法验算"
            elif verify_info["issues"]:
                extra = f"{n}人 ⚠验算差异{len(verify_info['issues'])}项: " + "; ".join(verify_info["issues"])
            else:
                extra = f"{n}人 ✓验算通过, 总和{verify_info['grand_sum']:.2f}"
        else:
            extra = f"{len(data_rows)}人 (无验算信息)"
        return (out_name, xlsx_b64, extra)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---- 工具⑤：美国 Humana 医疗账单 Details 提取 (复用 humana_details_extract) ----
def process_humana_details(filename, raw):
    tmpdir = tempfile.mkdtemp(prefix="humana_web_")
    try:
        pdf_path = os.path.join(tmpdir, _safe_filename(filename, default="humana.pdf"))
        with open(pdf_path, "wb") as f:
            f.write(raw)
        rows, verify_info = hum.extract_details(pdf_path)
        if not rows:
            print(f"[WARN] 未从 {filename} 提取到数据行（可能表格未识别/扫描件）")
            return None
        xlsx_path = os.path.join(tmpdir, "result.xlsx")
        hum.write_excel(rows, xlsx_path, verify_info)
        with open(xlsx_path, "rb") as f:
            xlsx_b64 = base64.b64encode(f.read()).decode("ascii")
        out_name = os.path.splitext(os.path.basename(filename))[0] + "_Details.xlsx"
        # extra_info: 行数 + 验算结果
        n = len(rows)
        if verify_info:
            nemp = len(verify_info.get("employees", []))
            emp_issues = [e for e in verify_info["employees"] if not e["ok"]]
            plan_issues = [p for p, d in verify_info.get("plan_totals", {}).items() if not d["ok"]]
            if emp_issues or plan_issues:
                extra = f"{n}行 ⚠差异{len(emp_issues)+len(plan_issues)}项(员工{len(emp_issues)}/计划{len(plan_issues)})"
            else:
                extra = f"{n}行 ✓验算通过({nemp}人)"
        else:
            extra = f"{n}行"
        return (out_name, xlsx_b64, extra)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---- 工具⑦：挪威工资单 PDF 提取 (复用 norway_pdf_parser + 标准模板) ----
_NORWAY_SUPPLIER_YAML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "norway_supplier.yaml")

# 字段中文名映射（英文 key -> 中文展示名）
_NORWAY_FIELD_CN = {
    "employee_name": "员工姓名",
    "period": "工资期间",
    "payment_date": "付款日期",
    "payslip_ref": "工资单编号",
    "ssn": "社保号(Fødselsnummer)",
    "net_pay": "本次实发",
    "account": "收款账号",
    "sum_payout": "合计实发",
}


def _payslip_line_text(line):
    return " ".join(w["text"] for w in line).strip()


def _payslip_find_header_line(lines, required_tokens):
    """找同时包含 required_tokens 中所有 token 的行。返回 (index, line) 或 (None,None)。"""
    for i, line in enumerate(lines):
        txt = _payslip_line_text(line).lower()
        if all(t.lower() in txt for t in required_tokens):
            return i, line
    return None, None


def _payslip_amount_in_line(line, belop_x=None, tol=90, strict=False):
    """从一行词中提取金额(挪威格式)。
    belop_x 为 Beløp 列 x 坐标: strict=True 时只在 belop_x 附近找, 不 fallback 到整行最右,
    避免描述行中的金额被误当成 Beløp; strict=False 时无命中则取整行最右数字。"""
    if belop_x is not None:
        cand = [w for w in line if abs(w["x0"] - belop_x) <= tol]
        if cand:
            cand.sort(key=lambda w: w["x0"])
            raw = " ".join(w["text"] for w in cand)
            v = npr.normalize_no_number(raw)
            if v is not None:
                return v, raw
        if strict:
            return None, ""
    # fallback: 整行最右可解析数字(紧凑空格)
    line_sorted = sorted(line, key=lambda w: w["x0"])
    full = " ".join(w["text"] for w in line_sorted)
    full = re.sub(r"-\s+", "-", full)
    last_val, last_raw = None, ""
    for mm in re.finditer(r"-?\d{1,3}(?:[ \u00a0\u202f]\d{3})*(?:,\d+)?", full):
        v = npr.normalize_no_number(mm.group(0))
        if v is not None:
            last_val, last_raw = v, mm.group(0)
    if last_val is not None:
        return last_val, last_raw
    return None, ""


_PAYSLIP_LABELS = re.compile(
    r"lønnslipp|lønnsbilag|for |utbetaling|adresse|periode|kontonummer|bank|"
    r"organisasjonsnummer|telefon|epost|e-post|dato|totalt|ansatt|arbeidsgiver|"
    r"bilag|referanse|beskrivelse|beløp|lønsart|skatte|trekk|brutto|netto|sum", re.I)


def _payslip_looks_like_name(txt):
    """判断文本是否像员工姓名(字母词、2-4个词、无数字/标签词)。"""
    if not txt or re.search(r"\d", txt) or _PAYSLIP_LABELS.search(txt):
        return False
    words = txt.split()
    if not (1 <= len(words) <= 4):
        return False
    for w in words:
        w0 = w.rstrip(".,")
        if not re.search(r"[A-Za-zæøåÆØÅ]", w0) or not re.match(r"^[A-ZÆØÅa-zæøå]", w0):
            return False
    return True


def _payslip_extract_header(words, lines):
    """提取工资单抬头信息(员工名/期间/付款日/实发/社保号/编号/Sum括号银行卡信息)。员工姓名在页面左上角。"""
    info = {}
    if not words:
        return info
    page_width = max(w["x0"] for w in words)
    mid = page_width / 2.0
    # 员工姓名: 页面左上角最上方、像人名且不含数字/标签词的文本行
    # (姓名通常在公司地址上方; 地址行带数字会被过滤掉)
    cands = []
    for line in lines:
        if not line:
            continue
        if not any(w["x0"] < mid for w in line):
            continue
        # 只取该行左半区的词(避免姓名与右上角标题同行被标签词污染)
        left_words = [w for w in line if w["x0"] < mid]
        txt = _payslip_line_text(left_words).strip()
        if _payslip_looks_like_name(txt):
            cands.append((line[0]["top"], txt))
    if cands:
        cands.sort(key=lambda x: x[0])
        info["employee_name"] = cands[0][1]
    # 基于标签行逐项提取
    for line in lines:
        txt = _payslip_line_text(line)
        ltxt = txt.lower()
        if "lønnslipp for" in ltxt:
            m = re.search(r"Lønnslipp for\s+([A-Za-zæøåÆØÅ]+\s+\d{4})", txt, re.I)
            if m:
                info["period"] = m.group(1)
        if "utbetalingsdato" in ltxt:
            m = re.search(r"\d{2}\.\d{2}\.\d{4}", txt)
            if m:
                info["payment_date"] = m.group(0)
        if "til utbetaling" in ltxt or "utbetales" in ltxt:
            v, _ = _payslip_amount_in_line(line)
            if v is not None:
                info["net_pay"] = v
        if "lønnsbilag:" in ltxt:
            m = re.search(r"Lønnsbilag:\s*(\S+)", txt, re.I)
            if m:
                info["payslip_ref"] = m.group(1)
        if "fødselsnummer:" in ltxt:
            m = re.search(r"Fødselsnummer:\s*(\d+)", txt, re.I)
            if m:
                info["ssn"] = m.group(1)
        # Sum 后括号里的银行卡信息
        msum = re.search(r"sum[^()]*\(([^()]*)\)", txt, re.I)
        if msum:
            info["bank_info"] = msum.group(1).strip()
            digits = re.sub(r"\D", "", msum.group(1))
            if digits:
                info["bank_account_clean"] = digits[-11:] if len(digits) >= 11 else digits
        # 兜底: 无括号但含 konto 的 Sum 行也抓账号
        elif "sum" in ltxt and "konto" in ltxt:
            m = re.search(r"konto\s+([A-Za-z]{0,2}\d[\d\s]+)", txt, re.I)
            if m:
                info["bank_info"] = m.group(1).strip()
                digits = re.sub(r"\D", "", m.group(1))
                if digits:
                    info["bank_account_clean"] = digits[-11:] if len(digits) >= 11 else digits
            v, _ = _payslip_amount_in_line(line)
            if v is not None:
                info["sum_payout"] = v
    return info


def _detect_payslip_header_colx(lines):
    """整份 PDF 共用列坐标检测: 扫描所有行, 优先返回同时含 Lønsart/Beskrivelse/Beløp 的表头行坐标。
    返回 {列名: x0}; 找不到则返回列最多的部分匹配。"""
    best = {}
    for i, line in enumerate(lines):
        lt = _payslip_line_text(line).lower()
        if not ("lønsart" in lt or "lønnsart" in lt or "beskrivelse" in lt or "beløp" in lt):
            continue
        colx = {}
        for li in lines[i:i + 5]:
            for w in li:
                t = w["text"].strip()
                for key in ("Lønsart", "Beskrivelse", "Antall", "Sats", "Grunnlag", "Beløp"):
                    tlo = t.lower()
                    klo = key.lower()
                    if klo in tlo or (klo == "lønsart" and "lønnsart" in tlo):
                        colx.setdefault(key, w["x0"])
        if "Lønsart" in colx and "Beskrivelse" in colx and "Beløp" in colx:
            return colx
        if len(colx) > len(best):
            best = colx
    return best


def _payslip_extract_month_table(lines, global_colx=None):
    """提取本月明细表: Lønsart/Beskrivelse/Antall/Sats/Grunnlag/Beløp。
    支持工资科目(描述)跨行、每行 Beløp 作行边界。
    global_colx: 整份 PDF 共用列坐标(由 _detect_payslip_header_colx 提供), 优先使用,
                 保证同一份单内所有员工块列宽一致, 避免部分员工 Lønsart/Beskrivelse 错位合并。"""
    # 定位表头: 含 lønsart/beskrivelse/beløp 任一关键词的行(兼容不同银行/雇主版式)
    hdr_idx = None
    for i, line in enumerate(lines):
        lt = _payslip_line_text(line).lower()
        if "lønsart" in lt or "lønnsart" in lt or "beskrivelse" in lt or "beløp" in lt:
            hdr_idx = i
            break
    if hdr_idx is None:
        return []
    # 列坐标: 优先用全局(整份单共用), 否则回退到本块局部检测
    colx = {}
    if global_colx:
        colx.update(global_colx)
    if "Beløp" not in colx or not ("Lønsart" in colx or "Beskrivelse" in colx):
        for line in lines[hdr_idx:hdr_idx + 5]:
            for w in line:
                t = w["text"].strip()
                for key in ("Lønsart", "Beskrivelse", "Antall", "Sats", "Grunnlag", "Beløp"):
                    tlo = t.lower()
                    klo = key.lower()
                    if (klo in tlo or (klo == "lønsart" and "lønnsart" in tlo)) and key not in colx:
                        colx[key] = w["x0"]
    # 必须有金额列 + 至少一个描述类列(否则无法确定工资科目); Lønsart 不再是硬性要求
    if "Beløp" not in colx or not ("Lønsart" in colx or "Beskrivelse" in colx):
        return []
    headers = sorted(colx.keys(), key=lambda k: colx[k])
    col_xs = [colx[c] for c in headers]
    # 列边界: 用固定 margin 替代相邻列中点。原因:
    #   - 中点法在 Beskrivelse(211) 与 Antall(392) 这种宽间距列之间会把边界定
    #     在 301.5, 导致 "(32,0%):" / "Rest" / "fribeløp:" 等描述性文本被切到 Antall。
    #   - margin=30pt 让 Beskrivelse 右边界直达 Antall 列左侧, 同时保证 Antall/Sats
    #     等窄列的值仍落在自己区间内。
    _COL_MARGIN = 30
    def col_of(x):
        for idx in range(len(col_xs)):
            lo = col_xs[idx] - _COL_MARGIN if idx > 0 else 0
            hi = col_xs[idx + 1] - _COL_MARGIN if idx < len(col_xs) - 1 else 1e9
            if lo <= x < hi:
                return headers[idx]
        return min(headers, key=lambda cn: abs(x - colx[cn]))
    def belop_amount(words):
        """取 Beløp 列(末列)区间内的数字组; 仅在该列区间内合并空格拆词, 避免跨列吞并 Antall/Grunnlag。
        兼容负号独立成词且紧贴左侧的写法。"""
        bw = [w for w in words if col_of(w["x0"]) == "Beløp"]
        if not bw:
            return None, ""
        bw = sorted(bw, key=lambda w: w["x0"])
        leftmost = bw[0]["x0"]
        extra = [w for w in words
                 if w["x0"] < leftmost and leftmost - w["x0"] <= 18
                 and w["text"].strip() in ("-", "–", "−")]
        allw = sorted(extra + bw, key=lambda w: w["x0"])
        raw = " ".join(w["text"] for w in allw)
        raw = re.sub(r"-\s+", "-", raw)
        v = npr.normalize_no_number(raw)
        if v is not None:
            return v, raw
        return None, ""
    # 工资科目(描述)列首词判定: 是否为"新科目行"。
    # 用途: 把 Timelønn / Skattetrekk / Fastlønn 等拆成独立行, 即使该科目行的 Beløp 列无金额
    # (例如 Skattetrekk 仅含 "Grunnlag fribeløp: ..." 文本、金额列空, 旧逻辑会把它并入上一行)。
    _SUBJECT_KW = {
        "fastlønn","timelønn","skattetrekk","bonus","feriepenger","sykelønn",
        "elektronisk","fast","naturalytelse","overtid","helgedag","skift",
        "tillegg","etterbetaling","forskudd","akkord","provisjon","pensjon",
        "forsikring","ferie","lønn",
    }
    _CONT_LEFT = {"utgiftsgodtgjørelse"}  # 在描述列首词、但属续行(包裹换行)的词
    antall_x = colx.get("Antall") or colx.get("Beskrivelse") or 0

    def _is_subject_start(line):
        if not line:
            return False
        lw = min(line, key=lambda w: w["x0"])  # 取最左词
        if antall_x and lw["x0"] > antall_x - 15:
            return False  # 不在描述列(首列)区域 -> 不是新科目
        t = lw["text"].strip().strip(":").lower()
        if t in _SUBJECT_KW:
            return True
        # 兜底: 描述列最左、首字母大写、且非已知续行词 -> 视为新科目(兼容未见过的工资类型)
        if lw["x0"] < 60 and t and t[0].isupper() and t not in _CONT_LEFT:
            return True
        return False

    rows = []
    pending = None
    for line in lines[hdr_idx + 1:]:
        txt = _payslip_line_text(line)
        if not txt:
            continue
        ltxt = txt.lower()
        if "totalt i" in ltxt or re.search(r"sum\s*\(", ltxt):
            break
        # Beløp 取 Beløp 列区间内的数字(末列)
        belop_num, belop_raw = belop_amount(line)
        # 按列区间归位
        cells = {h: [] for h in headers}
        for w in line:
            cells[col_of(w["x0"])].append(w)
        subject_start = _is_subject_start(line)
        if (not subject_start) and belop_num is None and pending is not None:
            # 延续上一行的描述或工资科目名(包裹换行的词)
            desc_txt = " ".join(w["text"] for w in cells.get("Beskrivelse", [])).strip()
            lønsart_txt = " ".join(w["text"] for w in cells.get("Lønsart", [])).strip()
            if desc_txt:
                pending["Beskrivelse"] = (pending.get("Beskrivelse", "") + " " + desc_txt).strip()
            if lønsart_txt:
                old = pending.get("Lønsart", "")
                pending["Lønsart"] = (old + " " + lønsart_txt).strip() if old else lønsart_txt
            continue
        # 新数据行(新科目 或 本行含 Beløp 金额)
        row = {"Beløp_num": belop_num, "Beløp_raw": belop_raw}
        for h in headers:
            row[h] = " ".join(w["text"] for w in cells.get(h, [])).strip()
        # Antall/Sats 应输出数值; 非数值文本(如 "Rest" / "fribeløp:" / 百分比描述)
        # 回流到 Beskrivelse, 因为它们是描述的一部分而非数量/单价。
        for num_col in ("Antall", "Sats"):
            raw = (row.get(num_col) or "").strip()
            if raw:
                v = npr.normalize_no_number(raw)
                if v is not None:
                    row[num_col] = v
                else:
                    # 回流到 Beskrivelse
                    row["Beskrivelse"] = ((row.get("Beskrivelse") or "") + " " + raw).strip()
                    row[num_col] = ""
        # 科目名兜底: 既无 Lønsart 也无 Beskrivelse 列时, 取整行去掉金额后的文本作为科目名
        if not row.get("Lønsart") and not row.get("Beskrivelse"):
            rest = txt
            if belop_raw:
                rest = rest.replace(belop_raw, "").strip()
            row["Beskrivelse"] = rest
        # 行内兜底拆分/修正:
        # 1) Lønsart 空但 Beskrivelse 以已知科目词开头 -> 首词归 Lønsart
        _b = (row.get("Beskrivelse") or "").strip()
        _fw = _b.split(" ", 1)[0] if _b else ""
        if not row.get("Lønsart") and _fw and _fw.lower() in _SUBJECT_KW:
            row["Lønsart"] = _fw
            row["Beskrivelse"] = _b[len(_fw):].strip()
        # 2) Lønsart 非空但 Beskrivelse 只剩连接符("-" / "–" / "−") -> 连接符应属科目名
        _b = (row.get("Beskrivelse") or "").strip()
        if row.get("Lønsart") and _b in ("-", "–", "−"):
            row["Lønsart"] = (row["Lønsart"] + " " + _b).strip()
            row["Beskrivelse"] = ""
        rows.append(row)
        pending = row
    return rows


def _payslip_extract_ytd_table(lines):
    """提取年度累计表: Beskrivelse / Beløp(在 'Totalt i 2026' 下方)。"""
    anchor_idx, _ = _payslip_find_header_line(lines, ["Totalt i"])
    if anchor_idx is None:
        return []
    hdr_idx, hdr_line = _payslip_find_header_line(lines[anchor_idx:], ["Beskrivelse", "Beløp"])
    if hdr_idx is None:
        return []
    hdr_idx += anchor_idx
    colx = {}
    for w in hdr_line:
        t = w["text"].strip()
        if "beskrivelse" in t.lower():
            colx["Beskrivelse"] = w["x0"]
        elif "beløp" in t.lower():
            colx["Beløp"] = w["x0"]
    if "Beløp" not in colx:
        return []
    belop_x = colx["Beløp"]
    rows = []
    pending = None
    for line in lines[hdr_idx + 1:]:
        txt = _payslip_line_text(line)
        if not txt:
            continue
        # 简单页脚过滤
        if re.search(r"side\s+\d+|page\s+\d+|www\.|@|bankgiro|organisasjonsnummer", txt, re.I):
            continue
        belop_num, belop_raw = _payslip_amount_in_line(line, belop_x=belop_x)
        cells_besk = [w for w in line if w["x0"] < belop_x - 20]
        besk = " ".join(w["text"] for w in sorted(cells_besk, key=lambda w: w["x0"])).strip()
        if belop_num is None and pending is not None and besk:
            pending["Beskrivelse"] = (pending.get("Beskrivelse", "") + " " + besk).strip()
            continue
        if belop_num is None:
            continue
        rows.append({"Beskrivelse": besk, "Beløp_raw": belop_raw, "Beløp_num": belop_num})
        pending = rows[-1]
    return rows


def _payslip_block_name(block):
    """从员工块首部取姓名: 姓名行含雇主 'YunExpress', 取 YunExpress 之前的文本为姓名。"""
    for line in block:
        txt = _payslip_line_text(line)
        if "yunexpress" in txt.lower():
            parts = re.split(r"yunexpress", txt, flags=re.I)
            name = parts[0].strip().rstrip("| ").strip()
            if name:
                return name
    return ""


def _payslip_extract_header_block(block):
    """在单个员工块内提取抬头信息(姓名/期间/付款日/实发/社保号/编号/Sum括号银行卡)。"""
    info = {}
    name = _payslip_block_name(block)
    if name:
        info["employee_name"] = name
    for line in block:
        txt = _payslip_line_text(line)
        ltxt = txt.lower()
        if "lønnslipp for" in ltxt:
            m = re.search(r"Lønnslipp for\s+([A-Za-zæøåÆØÅ]+\s+\d{4})", txt, re.I)
            if m:
                info["period"] = m.group(1)
        if "utbetalingsdato" in ltxt:
            m = re.search(r"\d{2}\.\d{2}\.\d{4}", txt)
            if m:
                info["payment_date"] = m.group(0)
        if "til utbetaling" in ltxt or "utbetales" in ltxt:
            v, _ = _payslip_amount_in_line(line)
            if v is not None:
                info["net_pay"] = v
        if "lønnsbilag:" in ltxt:
            m = re.search(r"Lønnsbilag:\s*(\S+)", txt, re.I)
            if m:
                info["payslip_ref"] = m.group(1)
        if "fødselsnummer:" in ltxt:
            m = re.search(r"Fødselsnummer:\s*(\d+)", txt, re.I)
            if m:
                info["ssn"] = m.group(1)
        msum = re.search(r"sum[^()]*\(([^()]*)\)", txt, re.I)
        if msum:
            info["bank_info"] = msum.group(1).strip()
            digits = re.sub(r"\D", "", msum.group(1))
            if digits:
                info["bank_account_clean"] = digits[-11:] if len(digits) >= 11 else digits
        elif "sum" in ltxt and "konto" in ltxt:
            m = re.search(r"konto\s+([A-Za-z]{0,2}\d[\d\s]+)", txt, re.I)
            if m:
                info["bank_info"] = m.group(1).strip()
                digits = re.sub(r"\D", "", m.group(1))
                if digits:
                    info["bank_account_clean"] = digits[-11:] if len(digits) >= 11 else digits
            v, _ = _payslip_amount_in_line(line)
            if v is not None:
                info["sum_payout"] = v
    # 实发兜底: 若上面没拿到, 用块内 'Sum(...)' 行的金额
    if "net_pay" not in info:
        for line in block:
            if re.search(r"sum\s*\(", _payslip_line_text(line).lower()):
                v, _ = _payslip_amount_in_line(line)
                if v is not None:
                    info["net_pay"] = v
                    break
    return info


def parse_norway_payslip_v2(pdf_path):
    """新版挪威工资单解析: 支持多页/多人批次(Lønnsbilag)。
    按 'Lønnsslipp for' 锚点把整份 PDF 切成多个员工块, 每块独立提取本月工资科目 + 抬头。
    返回 {'employees': [{'header':..., 'month_rows':[...]}, ...]}。"""
    if npr.pdfplumber is None:
        raise RuntimeError("请先安装 pdfplumber: pip install pdfplumber")
    all_words = []
    with npr.pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            offset = i * page.height
            for w in npr.get_words(page):
                all_words.append({"text": w["text"], "x0": w["x0"], "top": w["top"] + offset})
    if not all_words:
        return None
    lines = npr.get_lines(all_words, y_tol=6)
    # 全局表头检测: 整份 PDF 共用一套列坐标, 避免不同员工块列错位(Lønsart/Beskrivelse 合并)
    global_colx = _detect_payslip_header_colx(lines)
    # 员工锚点: 姓名行含雇主 YunExpress, 位于 Lønnsslipp for 之前;
    # 以姓名行为块起点, 才能把 姓名->本月科目->Sum->年度表 完整归到同一名员工。
    anchors = [i for i, line in enumerate(lines)
               if "yunexpress" in _payslip_line_text(line).lower()]
    if not anchors:
        # fallback: 其它雇主的单/多页工资单, 退而用 Lønnsslipp for 作为锚点
        anchors = [i for i, line in enumerate(lines)
                   if "lønnsslipp for" in _payslip_line_text(line).lower()]
    if not anchors:
        anchors = [0]
    employees = []
    for bi, a in enumerate(anchors):
        end = anchors[bi + 1] if bi + 1 < len(anchors) else len(lines)
        block = lines[a:end]
        header = _payslip_extract_header_block(block)
        month_rows = _payslip_extract_month_table(block, global_colx)  # 块内自带 'Sum(' 停止, 仅取本月科目
        name = header.get("employee_name", "")
        for r in month_rows:
            r["Navn"] = name
        employees.append({"header": header, "month_rows": month_rows})
    return {"employees": employees}


def _dump_payslip_debug(pdf_path, filename, data):
    """把解析结果 + 原始行坐标落到 debug_payslip_last.json, 便于排查真实版式(不影响输出)。"""
    import json as _json
    raw_lines = []
    try:
        with npr.pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                ws = npr.get_words(page)
                buckets = {}
                for w in ws:
                    key = round(w["top"] / 4) * 4
                    buckets.setdefault(key, []).append(w)
                for key in sorted(buckets):
                    wl = sorted(buckets[key], key=lambda w: w["x0"])
                    raw_lines.append(" | ".join("%s@%.0f" % (w["text"], w["x0"]) for w in wl))
    except Exception:
        pass
    employees = []
    if isinstance(data, dict):
        for e in data.get("employees", []):
            employees.append({
                "header": e.get("header", {}),
                "month_rows": e.get("month_rows", []),
            })
    out = {
        "filename": filename,
        "num_employees": len(employees),
        "employees": employees,
        "raw_lines": raw_lines,
    }
    try:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_payslip_last.json")
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(out, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def process_norway_payslip(filename, raw):
    tmpdir = tempfile.mkdtemp(prefix="nopsy_web_")
    try:
        pdf_path = os.path.join(tmpdir, _safe_filename(filename, default="norway_payslip.pdf"))
        with open(pdf_path, "wb") as f:
            f.write(raw)
        data = parse_norway_payslip_v2(pdf_path)
        employees = (data or {}).get("employees", []) if data else []
        if not employees:
            print(f"[WARN] 未从 {filename} 提取到工资单内容（可能非挪威工资单/扫描件）")
            return None
        xlsx_path = os.path.join(tmpdir, "result.xlsx")
        _write_norway_payslip_excel(data, xlsx_path)
        with open(xlsx_path, "rb") as f:
            xlsx_b64 = base64.b64encode(f.read()).decode("ascii")
        out_name = os.path.splitext(os.path.basename(filename))[0] + "_payslip.xlsx"
        # 逐员工校验: 本月明细 Beløp 合计 vs 该员工实发
        alerts = []
        lines_preview = []
        lines_preview.append("共 %d 名员工" % len(employees))
        lines_preview.append("=" * 44)
        for ei, emp in enumerate(employees, 1):
            h = emp.get("header", {})
            name = h.get("employee_name", "-")
            period = h.get("period", "-")
            net = h.get("net_pay", h.get("sum_payout"))
            rows = emp.get("month_rows", [])
            month_sum = sum(r.get("Beløp_num") or 0 for r in rows)
            mismatch = ""
            if net is not None and abs(month_sum - net) > 1.0:
                mismatch = "  ⚠本月合计%.2f≠实发%.2f" % (month_sum, net)
            bank_clean = h.get("bank_account_clean", "")
            lines_preview.append("### %d. %s | 期间 %s | 实发 %s | 卡后11位 %s" % (
                ei, name, period, ("%.2f" % net) if net is not None else "-", bank_clean))
            if rows:
                # 表格列与原单一致: Lønsart | Beskrivelse | Antall | Sats | Grunnlag | Beløp
                lines_preview.append("| Lønsart | Beskrivelse | Antall | Sats | Grunnlag | Beløp |")
                lines_preview.append("|---------|-------------|--------|------|----------|-------|")
                def _fmt_cell(v):
                    if v is None or v == "":
                        return ""
                    if isinstance(v, float) and v.is_integer():
                        return str(int(v))
                    return str(v).replace("\n", " ").replace("|", "/").strip()
                for r in rows:
                    la = _fmt_cell(r.get("Lønsart"))
                    be = _fmt_cell(r.get("Beskrivelse"))
                    an = _fmt_cell(r.get("Antall"))
                    sa = _fmt_cell(r.get("Sats"))
                    gr = _fmt_cell(r.get("Grunnlag"))
                    belop = r.get("Beløp_raw", "") or r.get("Beløp_num", "")
                    belop = "-" if belop == "" else str(belop).replace("\n", " ")
                    lines_preview.append("| %s | %s | %s | %s | %s | %s |" % (la, be, an, sa, gr, belop))
            else:
                lines_preview.append("(无本月科目)")
            if mismatch:
                lines_preview.append(mismatch)
                alerts.append("%s: %s" % (name, mismatch.strip()))
        if not alerts:
            lines_preview.append("✓ 各员工本月明细合计均与实发一致")
        else:
            lines_preview.append("⚠ 共 %d 名员工本月合计与实发不一致" % len(alerts))
        extra = "\n".join(lines_preview)
        # 调试落盘(对用户透明, 不影响输出/下载)
        try:
            _dump_payslip_debug(pdf_path, filename, data)
        except Exception:
            pass
        return (out_name, xlsx_b64, extra)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _write_norway_payslip_excel(data, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    hf = Font(bold=True, color="FFFFFF"); hfi = PatternFill("solid", fgColor="051D49")
    employees = (data or {}).get("employees", [])
    # Sheet 1: 本月工资明细(按员工展开, 姓名第一列)
    ws = wb.active
    ws.title = "本月工资明细"
    ws.append(["Navn(姓名)", "Lønsart(工资科目)", "Beskrivelse(描述)", "Antall",
               "Sats", "Grunnlag", "Beløp(原值)", "Beløp(数值)"])
    for c in ws[1]:
        c.font = hf; c.fill = hfi
    for emp in employees:
        for r in emp.get("month_rows", []):
            ws.append([r.get("Navn", ""), r.get("Lønsart", ""), r.get("Beskrivelse", ""),
                       r.get("Antall", ""), r.get("Sats", ""), r.get("Grunnlag", ""),
                       r.get("Beløp_raw", ""), r.get("Beløp_num", "")])
    # Sheet 2: 员工汇总(用于与付款清单 Konto/姓名比对)
    ws2 = wb.create_sheet("员工汇总")
    ws2.append(["Navn(姓名)", "工资期间", "实发金额", "银行卡(Sum括号)", "账号后11位",
                "社保号(Fødselsnummer)", "编号(Lønnsbilag)"])
    for c in ws2[1]:
        c.font = hf; c.fill = hfi
    for emp in employees:
        h = emp.get("header", {})
        net = h.get("net_pay", h.get("sum_payout"))
        ws2.append([h.get("employee_name", ""), h.get("period", ""),
                    ("%.2f" % net) if net is not None else "",
                    h.get("bank_info", ""), h.get("bank_account_clean", ""),
                    h.get("ssn", ""), h.get("payslip_ref", "")])

    # Sheet 3: 工资条(一人一行) —— 国内工资条习惯, 每个员工所有科目横向铺开
    # 中文短名映射(未知科目用挪威原词兜底)
    SUBJECT_ZH = {
        "Fastlønn": "固定工资", "Timelønn": "计时工资", "Skattetrekk": "个税预扣",
        "Bonus": "奖金", "Feriepenger": "度假费", "Sykelønn": "病假工资",
        "Overtid": "加班工资", "Ferietillegg": "度假附加",
        "Fast bilgodtgjørelse": "交通补贴",
        "Elektronisk kommunikasjon - utgiftsgodtgjørelse": "通讯补贴",
    }
    # 收集所有科目及属性(是否展开为工时/时薪/金额, 是否扣项)
    subj_info = {}
    for emp in employees:
        for r in emp.get("month_rows", []):
            subj = (r.get("Lønsart") or "").strip()
            if not subj:
                continue
            info = subj_info.setdefault(subj, {"count": 0, "expand": False, "deduct": False})
            info["count"] += 1
            an = r.get("Antall"); sa = r.get("Sats")
            if an not in (None, "") and sa not in (None, ""):
                info["expand"] = True
            b = r.get("Beløp_num")
            if b is not None and b < 0:
                info["deduct"] = True

    def zh_of(subj):
        return SUBJECT_ZH.get(subj, subj)

    adds = sorted([s for s, i in subj_info.items() if not i["deduct"]],
                  key=lambda s: -subj_info[s]["count"])
    dects = sorted([s for s, i in subj_info.items() if i["deduct"]],
                   key=lambda s: -subj_info[s]["count"])

    def cols_for(subj):
        info = subj_info[subj]
        zh = zh_of(subj)
        if info["expand"]:
            return [("%s·工时" % zh, subj, "Antall"),
                    ("%s·时薪" % zh, subj, "Sats"),
                    ("%s·金额" % zh, subj, "Belop")]
        return [("%s(%s)" % (zh, subj), subj, "Belop")]

    col_defs = []
    for s in adds:
        col_defs.extend(cols_for(s))
    for s in dects:
        col_defs.extend(cols_for(s))

    ws3 = wb.create_sheet("工资条(一人一行)")
    header3 = ["姓名", "工资期间"] + [c[0] for c in col_defs] + ["实发", "校验差", "卡后11位", "社保号"]
    ws3.append(header3)
    for c in ws3[1]:
        c.font = hf; c.fill = hfi

    for emp in employees:
        h = emp.get("header", {})
        net = h.get("net_pay", h.get("sum_payout"))
        # 聚合该员工各科目(同名科目多行则汇总)
        agg = {}
        for r in emp.get("month_rows", []):
            subj = (r.get("Lønsart") or "").strip()
            if not subj:
                continue
            a = agg.setdefault(subj, {"Antall": None, "Sats": None, "Belop": 0.0})
            b = r.get("Beløp_num")
            if b is not None:
                a["Belop"] += b
            an = r.get("Antall")
            if an not in (None, ""):
                try:
                    a["Antall"] = (a["Antall"] or 0) + float(an)
                except (ValueError, TypeError):
                    pass
            sa = r.get("Sats")
            if sa not in (None, "") and a["Sats"] is None:
                try:
                    a["Sats"] = float(sa)
                except (ValueError, TypeError):
                    a["Sats"] = sa
        row = [h.get("employee_name", ""), h.get("period", "")]
        total_belop = 0.0
        for (title, subj, field) in col_defs:
            a = agg.get(subj)
            if a is None:
                row.append("")
                continue
            if field == "Belop":
                if a["Belop"] == 0:
                    row.append("")  # 空金额科目(如免税 fribeløp)留空, 不写 0/假值
                else:
                    row.append(round(a["Belop"], 2))
                    total_belop += a["Belop"]
            else:
                v = a.get(field)
                row.append("" if v in (None, "") else v)
        row.append(round(net, 2) if net is not None else "")
        diff = (round(net, 2) - round(total_belop, 2)) if net is not None else ""
        row.append("" if isinstance(diff, (int, float)) and abs(diff) < 0.01 else diff)
        row.append(h.get("bank_account_clean", ""))
        row.append(h.get("ssn", ""))
        ws3.append(row)
    # 数值列格式(工资列/实发/校验差)
    num_cols = list(range(3, 3 + len(col_defs))) + [3 + len(col_defs), 3 + len(col_defs) + 1]
    for ri in range(2, ws3.max_row + 1):
        for ci in num_cols:
            cell = ws3.cell(row=ri, column=ci)
            if isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0.00"

    wb.save(path)


# ---- 工具⑧：挪威批量付款清单 PDF 提取 (Mottaker/KID/Konto/SWIFT/Beløp) ----
def _norway_line_amount(words_sorted):
    """从一行词(按 x0 升序)取最右完整挪威数字; 若被空格拆词(如 '12' '345,00')则向左合并还原。
    返回 (数值, 原文本); 无则返回 (None, '')。"""
    for i in range(len(words_sorted) - 1, -1, -1):
        if npr.normalize_no_number(words_sorted[i]["text"]) is not None:
            j = i
            while j - 1 >= 0 and re.match(r"^[0-9  ,\.]+$", words_sorted[j - 1]["text"]):
                j -= 1
            raw = " ".join(w["text"] for w in words_sorted[j:i + 1])
            return npr.normalize_no_number(raw), raw
    return None, ""


def _norway_merge_cells(words_sorted):
    """合并同一列被空格拆开的多个词为原字符串(用于 KID/Konto/SWIFT)。"""
    return " ".join(w["text"] for w in words_sorted)


# 付款清单表头 -> 规范列名 的识别表(兼容各银行版式写法)
_PAY_HDR_CANON = ["Mottaker", "KID", "Konto", "SWIFT", "Beløp", "Nr"]
_PAY_HDR_VARIANT = {
    "Betalt til": "Mottaker", "Mottaker/": "Mottaker", "Mottaker ": "Mottaker",
    "Kontonr": "Konto", "Kontonummer": "Konto", "Konto nr": "Konto", "Kontonr.": "Konto",
    "BIC": "SWIFT", "Swift": "SWIFT",
    "Amount": "Beløp", "Belop": "Beløp", "Beløp ": "Beløp", "Beløp eks": "Beløp",
    "Løpenr": "Nr", "Løpenummer": "Nr", "#": "Nr", "Nr.": "Nr", "Linje": "Nr",
}


def _pay_canon_header(text):
    t = (text or "").strip()
    if t in _PAY_HDR_CANON:
        return t
    return _PAY_HDR_VARIANT.get(t)


def _norway_col_amount(lw, belop_x, tol=80):
    """取 Beløp 列(锚定 belop_x)下的金额; 被空格拆词(如 '12' '345,00')则左右合并还原。
    belop_x 为 None 时回退为整行最右数字。返回 (数值, 原文本); 无则 (None,'')。"""
    cand_idx = []
    for i, w in enumerate(lw):
        if belop_x is not None and abs(w["x0"] - belop_x) > tol:
            continue
        if npr.normalize_no_number(w["text"]) is not None:
            cand_idx.append(i)
    if not cand_idx and belop_x is not None:
        # 回退: 整行最右数字
        for i in range(len(lw) - 1, -1, -1):
            if npr.normalize_no_number(lw[i]["text"]) is not None:
                cand_idx = [i]
                break
    if not cand_idx:
        return None, ""
    j = cand_idx[-1]
    lo, hi = j, j
    num_re = r"^[0-9 ,\.]+$"
    while lo - 1 >= 0 and re.match(num_re, lw[lo - 1]["text"]) and (
            belop_x is None or abs(lw[lo - 1]["x0"] - belop_x) <= tol):
        lo -= 1
    while hi + 1 < len(lw) and re.match(num_re, lw[hi + 1]["text"]) and (
            belop_x is None or abs(lw[hi + 1]["x0"] - belop_x) <= tol):
        hi += 1
    raw = " ".join(lw[k]["text"] for k in range(lo, hi + 1))
    return npr.normalize_no_number(raw), raw


def parse_norway_payment(pdf_path):
    """解析银行批量付款清单(动态识别表头列 + 按列 x 坐标归位):
    支持 序号(Nr)/Mottaker/KID/Konto/SWIFT/Beløp 各列, 金额严格锚定 Beløp 列,
    序号列与收款人自动拆分为两列, 底部 Sum/Total 行提取合计。
    返回 (rows, grand); rows 为 [{Nr,Mottaker,KID,Konto,SWIFT,Beløp,Beløp_num}], grand 为合计(或None)。"""
    if npr.pdfplumber is None:
        raise RuntimeError("请先安装 pdfplumber: pip install pdfplumber")
    rows = []
    grand = None
    with npr.pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = npr.get_words(page)
            if not words:
                continue
            # 定位表头行(取命中已知表头词的最上一行)
            hdr_hits = [w for w in words if _pay_canon_header(w["text"]) is not None]
            if not hdr_hits:
                continue
            hy = min(w["top"] for w in hdr_hits)
            colx = {}  # canon -> x0(取最左出现)
            for w in words:
                c = _pay_canon_header(w["text"])
                if c is not None and abs(w["top"] - hy) <= 8:
                    colx.setdefault(c, w["x0"])
            if "Beløp" not in colx:
                continue
            headers_ordered = sorted(colx.keys(), key=lambda k: colx[k])
            belop_x = colx.get("Beløp")
            has_nr_hdr = "Nr" in colx
            # 数据行按 top 分桶(容差4)
            data = [w for w in words if w["top"] > hy + 8]
            if not data:
                continue
            line_map = {}
            for w in data:
                key = round(w["top"] / 4) * 4
                line_map.setdefault(key, []).append(w)
            # 预检: 前几行最左词是否都是纯数字(无 Nr 表头时, 作为序号列剥离)
            lead_is_nr = False
            sample = [sorted(v, key=lambda w: w["x0"]) for v in list(line_map.values())[:3]]
            if not has_nr_hdr and sample and all(
                    r and re.match(r"^\d{1,8}$", r[0]["text"].strip()) for r in sample):
                lead_is_nr = True
            for key in sorted(line_map):
                lw = sorted(line_map[key], key=lambda w: w["x0"])
                if not lw:
                    continue
                texts = [w["text"] for w in lw]
                low = [t.lower() for t in texts]
                is_total = any(("sum" in t or "total" in t or "til sammen" in t) for t in low)
                if is_total:
                    v, _ = _norway_col_amount(lw, belop_x)
                    if v is not None:
                        grand = v
                    continue
                # 跳过页脚/说明行(无金额且非数据)
                belop_num, belop_raw = _norway_col_amount(lw, belop_x)
                if belop_num is None:
                    continue
                # 按最近表头 x 将每个词归位到列
                cells = {h: [] for h in headers_ordered}
                for w in lw:
                    best, bestd = None, 1e9
                    for h in headers_ordered:
                        d = abs(w["x0"] - colx[h])
                        if d < bestd:
                            bestd, best = d, h
                    if best is not None and bestd <= 90:
                        cells[best].append(w)
                # Mottaker + 序号剥离
                mwords = cells.get("Mottaker", [])
                nr = ""
                if has_nr_hdr:
                    nr = _norway_merge_cells(cells.get("Nr", []))
                elif lead_is_nr and mwords and re.match(r"^\d{1,8}$", mwords[0]["text"].strip()):
                    nr = mwords[0]["text"].strip()
                    mwords = mwords[1:]
                mottaker = _norway_merge_cells(mwords).strip()
                kid = _norway_merge_cells(cells.get("KID", []))
                konto = _norway_merge_cells(cells.get("Konto", []))
                swift = _norway_merge_cells(cells.get("SWIFT", []))
                # 账号派生: 去空格及特殊符号(仅留数字) + 取后11位
                konto_clean = re.sub(r"\D", "", konto or "")
                konto_last11 = konto_clean[-11:] if len(konto_clean) >= 11 else konto_clean
                rows.append({
                    "Nr": nr,
                    "Mottaker": mottaker,
                    "KID": kid,
                    "Konto": konto,
                    "Konto_clean": konto_clean,
                    "Konto_last11": konto_last11,
                    "SWIFT": swift,
                    "Beløp": belop_raw,
                    "Beløp_num": belop_num,
                })
    return rows, grand


def process_norway_payment(filename, raw):
    tmpdir = tempfile.mkdtemp(prefix="nopay_web_")
    try:
        pdf_path = os.path.join(tmpdir, _safe_filename(filename, default="norway_payment.pdf"))
        with open(pdf_path, "wb") as f:
            f.write(raw)
        rows, grand = parse_norway_payment(pdf_path)
        if not rows:
            print(f"[WARN] 未从 {filename} 提取到付款清单行（可能非付款清单/扫描件）")
            return None
        xlsx_path = os.path.join(tmpdir, "result.xlsx")
        _write_norway_payment_excel(rows, grand, xlsx_path)
        with open(xlsx_path, "rb") as f:
            xlsx_b64 = base64.b64encode(f.read()).decode("ascii")
        out_name = os.path.splitext(os.path.basename(filename))[0] + "_payment.xlsx"
        extra = "%d笔" % len(rows)
        if grand is not None:
            # 验算: 各笔金额之和是否等于底部 Sum
            s = sum(r["Beløp_num"] or 0 for r in rows)
            if abs(s - grand) > 0.01:
                extra += " ⚠合计不符(明细%.2f vs Sum %.2f)" % (s, grand)
            else:
                extra += " ✓合计%.2f一致" % grand
        else:
            extra += " (未识别底部Sum)"
        return (out_name, xlsx_b64, extra)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _write_norway_payment_excel(rows, grand, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "付款清单"
    headers = ["Nr(序号)", "Mottaker(收款人)", "KID", "Konto(原始账号)", "Konto(去符号)", "Konto(后11位)", "SWIFT", "Beløp(原值)", "Beløp(数值)"]
    ws.append(headers)
    hdr_fill = PatternFill("solid", fgColor="051D49")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = hdr_fill
    for r in rows:
        ws.append([r["Nr"], r["Mottaker"], r["KID"], r["Konto"], r["Konto_clean"],
                   r["Konto_last11"], r["SWIFT"], r["Beløp"], r["Beløp_num"]])
    if grand is not None:
        ws.append(["", "Sum(合计)", "", "", "", "", "", grand])
    wb.save(path)


# ---- 工具⑦+⑧ 集成入口：挪威单据自动识别 (工资单/付款清单) ----
def _detect_norway_doc_type(pdf_path):
    """返回 'payslip' / 'payment' / None（关键词命中计数，付款清单强特征优先）。"""
    if npr.pdfplumber is None:
        return None
    txt = ""
    with npr.pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            txt += " " + (page.extract_text() or "")
    txt = txt.lower()
    payslip_keys = ["lønnslip", "lønnsbilag", "brutto", "netto", "skattetrekk",
                    "feriepenger", "fødselsnummer", "utbetalingsdato", "lønnsart"]
    payment_keys = ["mottaker", "kid", "konto", "swift", "beløp", "payment summary"]
    s_pay = sum(k in txt for k in payslip_keys)
    s_pmt = sum(k in txt for k in payment_keys)
    # 付款清单特有词(Mottaker/KID/SWIFT)更专一，命中优先判 payment
    if s_pmt > 0 and (s_pmt >= s_pay or any(k in txt for k in ("mottaker", "kid", "swift"))):
        return "payment"
    if s_pay > 0:
        return "payslip"
    return None


def process_norway_doc(filename, raw):
    """集成入口：自动识别后分流到已有解析函数，复用其 Excel 输出。"""
    tmpdir = tempfile.mkdtemp(prefix="nodoc_web_")
    try:
        pdf_path = os.path.join(tmpdir, _safe_filename(filename, default="norway_doc.pdf"))
        with open(pdf_path, "wb") as f:
            f.write(raw)
        dtype = _detect_norway_doc_type(pdf_path)
        if dtype == "payment":
            return process_norway_payment(filename, raw)
        if dtype == "payslip":
            return process_norway_payslip(filename, raw)
        print(f"[WARN] {filename} 既不像工资单也不像付款清单，已跳过")
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---- 工具⑥：法国 Payfit import 自动填写 (复用 auto_fill_import) ----
def process_import_paie(filename, raw):
    if paie is None:
        raise RuntimeError("import 自动填写模块未加载，请检查 import-paie-autofill 技能脚本路径")
    import io, zipfile
    from openpyxl import load_workbook
    # 防止误传输出模板：如果文件名一看就是 import_variables_paie 模板，直接提示
    base_lc = os.path.basename(filename).lower()
    if base_lc.startswith("import_variables_paie"):
        raise RuntimeError(
            "你上传的是『import_variables_paie 输出模板』，不是输入源表。"
            "请上传每月工资合计-出勤统计表（需包含『出勤情况』和『工资合计』Sheet）。"
        )
    tmpdir = tempfile.mkdtemp(prefix="paie_web_")
    try:
        # 用原始文件名先推导年月，确保文件名携带 202607 等线索(下游 derive_ym 依赖文件名)
        # 可移植：默认取随包同目录的 import_templates，可用 PAIE_TEMPLATE_ROOT 覆盖
        tmpl_root = os.environ.get("PAIE_TEMPLATE_ROOT", os.path.join(_BASE, "import_templates"))
        _tmpl_hint = ""
        if os.path.isdir(tmpl_root):
            _hints = [d for d in os.listdir(tmpl_root) if os.path.isdir(os.path.join(tmpl_root, d))]
            _tmpl_hint = " ".join(_hints)
        _ym_early = paie.derive_ym(filename, _tmpl_hint)
        src_path = os.path.join(tmpdir, "_%s_%s" % (_ym_early, _safe_filename(filename, default="paie_source.xlsx")))
        with open(src_path, "wb") as f:
            f.write(raw)
        # 前置校验：输入源表必须同时包含「出勤情况」和「工资合计」Sheet
        try:
            wb = load_workbook(src_path, read_only=True, data_only=True)
            has_attendance = any("出勤情况" in s for s in wb.sheetnames)
            has_monthly = any("工资合计" in s for s in wb.sheetnames)
            wb.close()
        except Exception:
            has_attendance = has_monthly = False
        if not has_attendance:
            raise RuntimeError("未找到包含『出勤情况』的 Sheet，请确认上传的是每月工资合计-出勤统计源表，而不是 import_variables_paie 模板")
        if not has_monthly:
            raise RuntimeError("未找到包含『工资合计』的 Sheet，请确认上传的是每月工资合计-出勤统计源表")
        # ym 已在上文用原始文件名先推导, 这里复用 tmpl_root/_tmpl_hint 找对应模板目录
        ym = paie.derive_ym(src_path, _tmpl_hint)
        if ym == "UNKNOWN":
            raise RuntimeError("无法从文件名识别月份（需文件名含 202605 / 2026年05月 / 05月 之类；或在 import_templates 下建 <YYYYMM>- 子目录）")
        tmpl_dir = None
        if os.path.isdir(tmpl_root):
            for d in os.listdir(tmpl_root):
                dp = os.path.join(tmpl_root, d)
                if os.path.isdir(dp) and d.replace("-", "").startswith(ym):
                    tmpl_dir = dp
                    break
        if not tmpl_dir:
            raise RuntimeError("未找到模板目录: %s/%s-* （请在 import_templates 下建 <YYYYMM>- 子目录并放入 3 份空白模板）" % (tmpl_root, ym))
        outputs, unmatched = paie.run_fill(src_path, tmpl_dir, output_dir=tmpdir)
        if not outputs:
            return None
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in outputs:
                z.write(p, os.path.basename(p))
        zip_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        out_name = "import_paie_%s.zip" % ym
        if unmatched:
            extra = "⚠未匹配: " + "; ".join("%s:%s" % (k, ",".join(v)) for k, v in unmatched.items())
        else:
            extra = "3份全部匹配并生成"
        return (out_name, zip_b64, extra)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def process_import_paie_multi(payload):
    """多文件模式: 同时接收『每月工资合计-出勤统计表』(源表) + N份 import_variables_paie 空白模板。
    以模板人员为基准填充; 源表有但模板无的人不填写, 仅提示。
    payload: {"files": [{"filename": str, "data": base64}, ...]}
    返回 (out_name, zip_b64, extra_info)
    """
    if paie is None:
        raise RuntimeError("import 自动填写模块未加载，请检查 import-paie-autofill 技能脚本路径")
    import io, zipfile
    from openpyxl import load_workbook

    files = payload.get("files") if isinstance(payload, dict) else None
    if not files:
        raise RuntimeError("未收到任何文件，请同时上传源表与空白 import 模板")
    tmpdir = tempfile.mkdtemp(prefix="paie_web_")
    try:
        saved = []
        for f in files:
            fn = f.get("filename", "input.bin")
            raw = base64.b64decode(f.get("data", ""))
            p = os.path.join(tmpdir, _safe_filename(fn, default="paie_input.xlsx"))
            with open(p, "wb") as fh:
                fh.write(raw)
            saved.append((fn, p, raw))

        # 分类: 源表 (含出勤情况+工资合计 Sheet) vs 模板 (其余)
        source_path = None
        source_fn = None
        templates = []  # (filename, path)
        for fn, p, raw in saved:
            try:
                wb = load_workbook(p, read_only=True, data_only=True)
                has_att = any("出勤情况" in s for s in wb.sheetnames)
                has_mon = any("工资合计" in s for s in wb.sheetnames)
                wb.close()
            except Exception:
                has_att = has_mon = False
            if has_att and has_mon:
                if source_path is not None:
                    raise RuntimeError("收到多份源表（均含『出勤情况』+『工资合计』），请只上传一份每月工资合计-出勤统计表")
                source_path, source_fn = p, fn
            else:
                templates.append((fn, p))

        if source_path is None:
            raise RuntimeError("未找到源表（需含『出勤情况』+『工资合计』Sheet）。请上传每月工资合计-出勤统计表，不要只传 import 模板")
        if not templates:
            raise RuntimeError("未找到 import 空白模板。请一并上传 import_variables_paie-YYYYMM <地点>.xlsx 空白版（可多份）")

        outputs, report = paie.run_fill_v2(source_path, [t[1] for t in templates], output_dir=tmpdir)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for p in outputs:
                z.write(p, os.path.basename(p))
        zip_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        out_name = "import_paie_自动生成.zip"

        # 组装提示文案
        lines = []
        for fn, cnt in report["filled"].items():
            lines.append("%s：填 %d 人" % (fn, cnt))
        if report.get("template_missing"):
            tm = "; ".join("%s: %s" % (k, ", ".join(v)) for k, v in report["template_missing"].items())
            lines.append("⚠ 模板有但源表无匹配（保持空白）: " + tm)
        if report.get("source_extra"):
            lines.append("⚠ 源表有但模板无（未填写，仅提示）: " + ", ".join(report["source_extra"]))
        extra = "\n".join(lines) if lines else "全部匹配并生成"
        return (out_name, zip_b64, extra)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---- 工具⑨：意大利工资单 PDF 提取 (复用 italy_payslip_parser) ----
def process_italy_payslip(filename, raw):
    tmpdir = tempfile.mkdtemp(prefix="itpay_web_")
    try:
        safe_name = _safe_filename(filename, default="italy_payslip.pdf")
        pdf_path = os.path.join(tmpdir, safe_name)
        with open(pdf_path, "wb") as f:
            f.write(raw)
        wb_bytes, info = ita.run(pdf_path)
        if not info or not info.get("num_employees"):
            print(f"[WARN] 未从 {filename} 提取到员工（可能非意大利工资单/扫描件）")
            return None
        xlsx_b64 = base64.b64encode(wb_bytes).decode("ascii")
        out_name = os.path.splitext(os.path.basename(filename))[0] + "_italy.xlsx"
        extra = "%d名员工 / %d条费用 / %d个编码" % (
            info.get("num_employees", 0), info.get("num_voci", 0), info.get("num_codes", 0))
        return (out_name, xlsx_b64, extra)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---- 工具⑩：荷兰工资单 PDF 提取 (复用 dutch_payslip_parser) ----
def process_dutch_payslip(filename, raw):
    tmpdir = tempfile.mkdtemp(prefix="dupa_web_")
    try:
        safe_name = _safe_filename(filename, default="dutch_payslip.pdf")
        pdf_path = os.path.join(tmpdir, safe_name)
        with open(pdf_path, "wb") as f:
            f.write(raw)
        wb_bytes, info = dpa.run(pdf_path)
        if not info or not info.get("num_employees"):
            print(f"[WARN] 未从 {filename} 提取到员工（可能非荷兰工资单/扫描件）")
            return None
        xlsx_b64 = base64.b64encode(wb_bytes).decode("ascii")
        out_name = os.path.splitext(os.path.basename(filename))[0] + "_dutch.xlsx"
        extra = "%d名员工 / %d条明细" % (
            info.get("num_employees", 0), info.get("num_detail", 0))
        return (out_name, xlsx_b64, extra)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def process_dutch_payslip_multi(payload):
    """批量处理多个荷兰工资单 PDF，合并为一个 Excel（Sheet1 工资明细 + Sheet2 员工汇总）。"""
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    files = payload.get("files", [])
    if not files:
        return None
    master_wb = Workbook()
    master_wb.remove(master_wb.active)
    ws1 = master_wb.create_sheet("工资明细")
    ws2 = master_wb.create_sheet("员工汇总")
    total_emp = 0
    total_detail = 0
    thin = Side(style="thin", color="D0D7DE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="1F4E78")
    head_font = Font(bold=True, color="FFFFFF", size=10)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    money_fmt = "#.##0,00"
    first = True
    for fobj in files:
        filename = fobj.get("filename", "input.pdf")
        data = base64.b64decode(fobj.get("data", ""))
        if not data:
            continue
        tmpdir = tempfile.mkdtemp(prefix="dupa_web_")
        try:
            safe_name = _safe_filename(filename, default="dutch_payslip.pdf")
            pdf_path = os.path.join(tmpdir, safe_name)
            with open(pdf_path, "wb") as f:
                f.write(data)
            wb_bytes, info = dpa.run(pdf_path)
            if not info or not info.get("num_employees"):
                continue
            total_emp += info.get("num_employees", 0)
            total_detail += info.get("num_detail", 0)
            tmp_xlsx = os.path.join(tmpdir, "out.xlsx")
            with open(tmp_xlsx, "wb") as f:
                f.write(wb_bytes)
            wb = load_workbook(tmp_xlsx, data_only=True)
            s1 = wb["工资明细"]
            s2 = wb["员工汇总"]
            if first:
                # Sheet1 表头
                for row in s1.iter_rows(min_row=1, max_row=1, values_only=False):
                    for c in row:
                        nc = ws1.cell(row=1, column=c.column, value=c.value)
                        nc.fill = head_fill; nc.font = head_font; nc.alignment = center; nc.border = border
                # Sheet2 双表头
                for row in s2.iter_rows(min_row=1, max_row=2, values_only=False):
                    for c in row:
                        nc = ws2.cell(row=c.row, column=c.column, value=c.value)
                        nc.fill = head_fill; nc.font = head_font; nc.alignment = center; nc.border = border
                first = False
            # 复制 Sheet1 数据行
            for row in s1.iter_rows(min_row=2, values_only=True):
                ws1.append(row)
            # 复制 Sheet2 数据行
            for row in s2.iter_rows(min_row=3, values_only=True):
                ws2.append(row)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    if first:
        return None
    # 应用格式
    for ws in (ws1, ws2):
        for row in ws.iter_rows(min_row=3 if ws == ws2 else 2):
            for c in row:
                c.border = border
                c.alignment = center
                if isinstance(c.value, (int, float)) and c.column >= 5:
                    c.number_format = money_fmt
    # 列宽：从最后一个 wb 的列宽复制（所有 wb 结构一致）
    # 简单按固定比例
    widths1 = [16, 10, 12, 8, 26, 10, 9, 11, 11, 11, 9, 8, 9, 11, 7]
    for i, w in enumerate(widths1, 1):
        ws1.column_dimensions[get_column_letter(i)].width = w
    widths2 = [6, 16, 10, 12, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11,
               11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11,
               10, 11, 11, 11, 11, 12, 12, 12, 12, 10]
    for i, w in enumerate(widths2, 1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    ws1.freeze_panes = "A2"
    ws2.freeze_panes = "A3"
    if ws1.max_row > 1:
        ws1.auto_filter.ref = "A1:O%d" % ws1.max_row
    if ws2.max_row > 2:
        ws2.auto_filter.ref = "A1:%s%d" % (get_column_letter(ws2.max_column), ws2.max_row)
    buf = io.BytesIO()
    master_wb.save(buf)
    out_bytes = buf.getvalue()
    xlsx_b64 = base64.b64encode(out_bytes).decode("ascii")
    out_name = "dutch_payslips_batch_%dfiles.xlsx" % len(files)
    extra = "%d名员工 / %d条明细" % (total_emp, total_detail)
    return (out_name, xlsx_b64, extra)


register_tool(
    "swedish_tax", "瑞典税务 PDF 提取",
    "按人提取 Ruta / Namn / Värde, 金额自动规范化, 输出 Excel 双表 (Ruta明细 + 金额透视)。",
    process_swedish_tax, accept=".pdf", enabled=True,
    en_name="SWEDISH TAX PDF EXTRACTOR",
    version="v1.0",
    status_text="稳定主模块",
    last_batch="2026-08",
    last_result="29人",
    category="海外核算",
    country="瑞典",
)

# ---- 工具②、③：占位 (新增工具只需在此加一行 register_tool) ----
register_tool(
    "payroll", "工资单处理",
    "工资单批量解析、异常复核与结果导出。",
    None, "", enabled=False,
    en_name="PAYROLL PROCESSING",
    version="v0.2",
    status_text="试运行",
    last_batch="-",
    last_result="-",
    category="工资核算",
    country="中国",
)
register_tool(
    "invoice", "发票识别",
    "海外劳务报账发票 OCR 识别与结构化核对。",
    None, "", enabled=False,
    en_name="OVERSEAS INVOICE AUDIT",
    version="v0.5-UAT",
    status_text="试运行",
    last_batch="-",
    last_result="-",
    category="海外核算",
    country="中国",
)

# ---- 工具④：荷兰养老金提取 (已上线) ----
register_tool(
    "dutch_pension", "荷兰养老金提取",
    "解析 Zwitserleven 荷兰养老金 PDF 账单, 按标准 9 列结构提取并输出 Excel (含金额透视)。",
    process_dutch_pension, accept=".pdf", enabled=True,
    en_name="DUTCH PENSION PDF EXTRACTOR",
    version="v1.0",
    status_text="已上线",
    last_batch="2026-08",
    last_result="-",
    category="海外核算",
    country="荷兰",
)

# ---- 工具⑤：Humana 牙科/眼科明细提取 (已上线) ----
register_tool(
    "humana_details", "Humana 牙科/眼科",
    "提取美国 Humana 医疗账单 Details 区域: Policy / Name / Coverage / Period / Code / 金额。",
    process_humana_details, accept=".pdf", enabled=True,
    en_name="HUMANA MEDICAL DETAILS EXTRACTOR",
    version="v1.0",
    status_text="已上线",
    last_batch="2026-08",
    last_result="-",
    category="海外核算",
    country="美国",
)

# ---- 工具⑥：法国 Payfit import 自动填写 (已上线) ----
register_tool(
    "import_paie", "法国 Payfit import 自动填写",
    "一次上传『每月工资合计-出勤统计表』(源表, 需含出勤情况+工资合计 Sheet) + N份 import_variables_paie-YYYYMM <地点>.xlsx 空白模板。以模板人员为基准匹配填充：模板有而源表无的人保持空白；源表有而模板无的人不填写，仅提示。输出每份填好的 xlsx 打包下载。",
    process_import_paie, accept=".xlsx", enabled=True,
    process_multi=process_import_paie_multi,
    en_name="FR PAYFIT IMPORT AUTO-FILL",
    version="v2.0",
    status_text="已上线",
    last_batch="2026-05",
    last_result="按模板",
    category="工资核算",
    country="法国",
)

# ---- 工具⑦：挪威工资单 PDF 提取 (已上线) ----
register_tool(
    "norway_payslip", "挪威工资单 PDF 提取",
    "上传挪威工资单(Lønnslip) PDF，自动提取员工姓名、期间、实发金额与银行卡信息，并逐行列出每个工资科目（基本工资/交通补贴/个税等）的名称与金额，导出 Excel。先预览确认再下载。",
    process_norway_payslip, accept=".pdf", enabled=True,
    en_name="NORWAY PAYSLIP EXTRACTOR",
    version="v2.1",
    status_text="已上线",
    last_batch="2026-08",
    last_result="-",
    category="海外核算",
    preview=True,
    country="挪威",
)

# ---- 工具⑧：挪威付款清单 PDF 提取 (已上线) ----
register_tool(
    "norway_payment", "挪威付款清单 PDF 提取",
    "上传银行批量付款清单 PDF，自动识别表头并按列归位，提取序号/收款人/KID/账号(含去符号与后11位)/SWIFT/Beløp 金额并导出 Excel。先预览确认再下载。",
    process_norway_payment, accept=".pdf", enabled=True,
    en_name="NORWAY PAYMENT EXTRACTOR",
    version="v2.1",
    status_text="已上线",
    last_batch="2026-08",
    last_result="-",
    category="海外核算",
    preview=True,
    country="挪威",
)


# ---- 工具⑨：意大利工资单 PDF 提取 (已上线) ----
register_tool(
    "italy_payslip", "意大利工资单 PDF 提取",
    "上传意大利工资单 PDF，自动识别员工（编号/姓名/税号）、按坐标提取各项工资科目（importo base / riferimento / trattenute / competenze）及汇总（净薪/总应发/总扣），导出 Excel 三表（Voci Variabili / RIEPILOGO / INFORMAZIONI）。",
    process_italy_payslip, accept=".pdf", enabled=True,
    en_name="ITALY PAYSLIP EXTRACTOR",
    version="v1.0",
    status_text="已上线",
    last_batch="2026-08",
    last_result="-",
    category="海外核算",
    country="意大利",
)

# ---- 工具⑩：荷兰工资单 PDF 提取 (已上线) ----
register_tool(
    "dutch_payslip", "荷兰工资单 PDF 提取",
    "上传荷兰工资单 PDF (如 CIRRO Loonstrook)，按 Salarisspecificatie 标记自动分组员工，提取主表明细 (Code/Omschrijving/Betaling/Inhouding/Werkgever 等) 与附录汇总 (Reservering/Fiscaal loon/SVW loon/考勤)，导出 Excel 双表 (工资明细 / 员工汇总，含成本合计)。",
    process_dutch_payslip, accept=".pdf", enabled=True,
    process_multi=process_dutch_payslip_multi,
    en_name="DUTCH PAYSLIP EXTRACTOR",
    version="v1.0",
    status_text="已上线",
    last_batch="2026-08",
    last_result="-",
    category="海外核算",
    country="荷兰",
)


# ---------------------------------------------------------------------------
# 飞书 token 换取 (secret 仅在此函数内使用, 绝不下发前端)
# ---------------------------------------------------------------------------
def feishu_exchange_code(code):
    """用授权码换 access_token, 再换 userinfo。返回 (token_info, user_info)。"""
    if CFG.get("feishu_mocked"):
        # 仅本地测试: 不真正请求飞书
        return (
            {"access_token": "mock_token", "open_id": "mock_open_id_test"},
            {"open_id": "mock_open_id_test", "name": "测试用户(模拟)", "tenant_key": "mock_tenant"},
        )
    data = {
        "app_id": CFG["app_id"],
        "app_secret": CFG["app_secret"],
        "code": code,
        "grant_type": "authorization_code",
    }
    req = urllib.request.Request(
        CFG["token_url"],
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        j = json.loads(resp.read().decode("utf-8"))
    if j.get("code") != 0:
        raise Exception("飞书换取令牌失败: " + str(j.get("msg", "")))
    tk = j["data"]["access_token"]
    open_id = j["data"].get("open_id")
    req2 = urllib.request.Request(
        CFG["userinfo_url"],
        headers={"Authorization": "Bearer " + tk},
    )
    with urllib.request.urlopen(req2, timeout=10) as resp2:
        j2 = json.loads(resp2.read().decode("utf-8"))
    if j2.get("code") != 0:
        raise Exception("飞书获取用户信息失败: " + str(j2.get("msg", "")))
    u = j2["data"]
    return ({"access_token": tk, "open_id": open_id},
            {"open_id": u.get("open_id"), "name": u.get("name"), "tenant_key": u.get("tenant_key")})


# ---------------------------------------------------------------------------
# Cookie / 响应辅助
# ---------------------------------------------------------------------------
def make_cookie(name, value, max_age=None, secure=False, same_site="Lax"):
    s = "%s=%s; Path=/; HttpOnly" % (name, value)
    if same_site:
        s += "; SameSite=%s" % same_site
    if secure:
        s += "; Secure"
    if max_age is not None:
        s += "; Max-Age=%d" % max_age
    return s


def clear_cookie(name, secure=False, same_site="Lax"):
    s = "%s=; Path=/; HttpOnly" % name
    if same_site:
        s += "; SameSite=%s" % same_site
    if secure:
        s += "; Secure"
    s += "; Max-Age=0"
    return s


def parse_cookies(handler):
    out = {}
    ch = handler.headers.get("Cookie", "")
    for part in ch.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def simple_html(title, msg):
    return ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<title>%s</title><style>body{font-family:-apple-system,'Microsoft YaHei',sans-serif;"
            "background:#f0f4f8;color:#1a1a1a;display:flex;min-height:100vh;align-items:center;"
            "justify-content:center}h1{color:#cf1322;font-size:20px}"
            ".box{background:#fff;border:1px solid #e1e8f0;border-radius:12px;padding:28px 36px;"
            "text-align:center;box-shadow:0 2px 12px rgba(13,27,42,.06)}p{color:#596475;margin:10px 0 0;line-height:1.6}"
            "a{color:#ED7D31;text-decoration:none;font-weight:600}</style></head>"
            "<body><div class='box'><h1>%s</h1><p>%s</p>"
            "<p style='margin-top:18px'><a href='/'>返回工作台</a></p></div></body></html>"
            ) % (title, title, msg)


# ---------------------------------------------------------------------------
# 前端网页 (Workbench 风格: 左侧导航 + 顶部搜索/用户 + 模块卡片网格)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 前端网页 (Workbench 风格): 模板独立为 templates/index.html
# 运行时读取 (dev 改模板刷新即生效; 打包态读 _MEIPASS). 占位符:
#   __PASSCODE_HINT__ / __NO_AUTH__ 由 do_GET 替换
# ---------------------------------------------------------------------------
def load_page_html():
    import os as _os, sys as _sys
    _base = _os.path.dirname(_os.path.abspath(__file__))
    _cands = []
    if getattr(_sys, "frozen", False):
        _cands.append(_os.path.join(_sys._MEIPASS, "templates", "index.html"))
    _cands.append(_os.path.join(_base, "templates", "index.html"))
    for _p in _cands:
        if _os.path.exists(_p):
            with open(_p, encoding="utf-8") as _f:
                return _f.read()
    raise FileNotFoundError("templates/index.html 未找到, 搜索路径: " + ", ".join(_cands))



# ---------------------------------------------------------------------------
# HTTP 处理
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json", cookies=None, extra_headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        # 禁止浏览器缓存页面与接口响应，避免回跳后加载到旧版 HTML（无 sid 提取逻辑）导致“仍显示未登录”
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        for c in (cookies or []):
            self.send_header("Set-Cookie", c)
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _current_user(self):
        if NO_AUTH:
            # 免登录模式：直接放行，返回匿名已登录用户态（不校验任何口令/会话）
            return {"open_id": "anon", "name": "免登录用户", "tenant_key": "",
                    "first_login": False, "login_at": int(time.time()), "anon": True}
        # 优先从 Authorization: Bearer <sid> 头读取（跨站/隧道场景绕开 cookie 被浏览器阻止）
        auth = self.headers.get("Authorization", "")
        sid = ""
        src = "none"
        if auth.startswith("Bearer "):
            sid = auth[7:].strip()
            src = "bearer"
        if not sid:
            sid = parse_cookies(self).get("sid")
            if sid:
                src = "cookie"
        dlog("CURRENT_USER src=%s sid8=%s" % (src, sid[:8] if sid else None))
        if not sid:
            return None
        u = SESSIONS.get(sid)
        if not u:
            dlog("CURRENT_USER miss sid8=%s" % (sid[:8] if sid else None))
            return None
        if time.time() - u.get("ts", 0) > SESSION_TTL:
            SESSIONS.pop(sid, None)
            dlog("CURRENT_USER expired sid8=%s" % (sid[:8] if sid else None))
            return None
        return u

    def _localhost_root(self):
        """返回 localhost 根地址（必须和飞书回调地址同域同端口）。"""
        ru = CFG.get("redirect_uri", "http://localhost:8765/feishu/callback")
        p = urllib.parse.urlparse(ru)
        return "%s://localhost:%s/" % (p.scheme or "http", p.port or 8765)

    def _is_localhost_host(self):
        host = self.headers.get("Host", "").lower()
        return host.startswith("localhost:") or host == "localhost"

    def _dyn_redirect_uri(self):
        """动态构造飞书回调地址，跟随实际访问 host 与 scheme（支持内网共享 / https 隧道）。

        飞书 OAuth 授权时 redirect_uri 必须与开放平台后台白名单精确匹配：
        - 同事通过 http://<内网IP>:8765 访问 → http://<内网IP>:8765/feishu/callback
        - 通过 https 隧道（如 *.trycloudflare.com）访问 → https://<隧道域名>/feishu/callback
        隧道（cloudflared）转发请求时会带上 X-Forwarded-Proto / X-Forwarded-Host 头，
        据此判定真实协议与主机，避免回调地址被写死成 http 导致飞书拒绝授权。
        """
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").strip()
        if not host:
            return CFG.get("redirect_uri", "http://localhost:8765/feishu/callback")
        scheme = self._scheme_of()
        return "%s://%s/feishu/callback" % (scheme, host)

    def _scheme_of(self):
        """稳健判定当前访问的真实协议（http/https）。

        优先级：
        1) X-Forwarded-Proto 头（隧道/反代显式携带）→ 直接采用
        2) Host 含 trycloudflare.com 等公网隧道域名 → 必为 https
        3) localhost / 127.x / 纯 IP → 内网直连, http
        4) 其它公网域名 → 默认 https
        避免「无 X-Forwarded-Proto 时把隧道 https 误判成 http」导致回跳地址变成
        http://隧道域名/... 而隧道只服务 https, 回跳失败、登录态永远拿不到。
        """
        proto = (self.headers.get("X-Forwarded-Proto") or "").strip().lower()
        if proto in ("http", "https"):
            return proto
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").lower()
        if "trycloudflare.com" in host:
            return "https"
        if host.startswith("localhost") or host.startswith("127."):
            return "http"
        if re.match(r"^\d+(\.\d+){3}", host.split(":")[0]):
            return "http"
        return "https"

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path
        if p in ("/", ""):
            self._send(200, load_page_html().replace("__PASSCODE_HINT__", _PASSCODE_HINT_HTML).replace("__NO_AUTH__", "true" if NO_AUTH else "false"), "text/html")
        elif p == "/api/me":
            user = self._current_user()
            if user:
                self._send(200, json.dumps({"user": {
                    "open_id": user["open_id"], "name": user.get("name"),
                    "tenant_key": user.get("tenant_key"), "first_login": user.get("first_login"),
                    "login_at": user.get("login_at"), "anon": bool(user.get("anon")),
                }, "passcode_mode": bool(SHARE_PASSCODE) and not NO_AUTH}))
            else:
                self._send(200, json.dumps({"user": None, "passcode_mode": bool(SHARE_PASSCODE) and not NO_AUTH}))
        elif p == "/api/tools":
            self.serve_tools()
        elif p == "/login/feishu":
            self._send(302, "", extra_headers={"Location": "/"})
        elif p == "/feishu/callback":
            self._send(302, "", extra_headers={"Location": "/"})
        elif p == "/logout":
            self.serve_logout()
        else:
            self._send(404, json.dumps({"ok": False, "error": "not found"}))

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        parts = [x for x in u.path.split("/") if x]
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "tool" and parts[-1] == "process":
            self.serve_tool_process(parts[2])
        elif len(parts) == 2 and parts[0] == "api" and parts[1] == "unlock":
            self.serve_unlock()
        elif len(parts) == 2 and parts[0] == "api" and parts[1] == "change-passcode":
            self.serve_change_passcode()
        else:
            self._send(404, json.dumps({"ok": False, "error": "not found"}))

    # ---- 工具列表 (首页卡片用) ----
    def serve_tools(self):
        lst = []
        for t in TOOLS.values():
            if not t.get("enabled", True):
                continue  # 未启用的工具不在前端工作台展示
            lst.append({
                "id": t["id"], "name": t["name"], "desc": t["desc"],
                "accept": t.get("accept", ""), "enabled": t.get("enabled", True),
                "en_name": t.get("en_name", ""), "version": t.get("version", ""),
                "status_text": t.get("status_text", ""), "last_batch": t.get("last_batch", ""),
                "last_result": t.get("last_result", ""), "category": t.get("category", ""),
                "btn_text": t.get("btn_text", ""),
                "country": t.get("country", "通用"),
                "multi": bool(t.get("process_multi")),
                "preview": bool(t.get("preview")),
            })
        self._send(200, json.dumps({"tools": lst}))

    # ---- 工具处理 (需登录) ----
    def serve_tool_process(self, tool_id):
        user = self._current_user()
        if not user:
            self._send(200, json.dumps({"ok": False, "error": "请先通过共享口令登录后再操作"}))
            return
        tool = TOOLS.get(tool_id)
        if not tool or not tool.get("enabled") or not tool.get("process"):
            self._send(200, json.dumps({"ok": False, "error": "工具不可用或已停用"}))
            return
        _ensure_modules()  # 惰性加载 PDF/import 重依赖（fitz/pdfplumber 等），降低常驻内存
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
            mask = bool(payload.get("mask", False))

            t0 = time.time()
            # 多文件模式: 前端一次性传 {"files":[{filename,data}...]}
            if isinstance(payload, dict) and isinstance(payload.get("files"), list) and tool.get("process_multi"):
                filename = payload["files"][0].get("filename", "input.bin") if payload["files"] else "input.bin"
                in_bytes = sum(len(base64.b64decode(f.get("data", ""))) for f in payload["files"])
                result = tool["process_multi"](payload)
            else:
                filename = payload.get("filename", "input.bin")
                b64 = payload.get("data", "")
                data = base64.b64decode(b64)
                in_bytes = len(data)
                result = tool["process"](filename, data)
            elapsed_ms = int((time.time() - t0) * 1000)

            # 工具返回 None 或 (None, None, "具体原因") 表示未提取到有效数据
            if result is None or (isinstance(result, tuple) and result[0] is None):
                detail_err = None
                if isinstance(result, tuple) and len(result) > 2 and result[2]:
                    detail_err = str(result[2])
                try:
                    _raw = data
                except NameError:
                    _raw = None
                diag = _diagnose_failure(tool.get("id", ""), filename, _raw, detail_err)
                self._send(200, json.dumps({"ok": False, "error": diag}))
                return

            # result: (out_name, out_b64) 或 (out_name, out_b64, extra_info)
            if isinstance(result, tuple):
                out_name = result[0]
                out_b64 = result[1]
                info = result[2] if len(result) > 2 else None
            else:
                out_name, out_b64, info = result, None, None

            # 导出脱敏（统一出口后处理，不改动任何 parser）
            if mask and out_b64:
                try:
                    out_b64 = mask_xlsx(out_b64)
                    if out_name:
                        _bn, _ext = os.path.splitext(out_name)
                        out_name = _bn + "（脱敏版）" + _ext
                except Exception:
                    pass  # 兜底：脱敏失败不影响正常导出

            out_bytes = len(base64.b64decode(out_b64)) if out_b64 else 0
            sheets = None
            if out_b64:
                try:
                    from io import BytesIO
                    from openpyxl import load_workbook
                    wb = load_workbook(BytesIO(base64.b64decode(out_b64)))
                    sheets = len(wb.sheetnames)
                except Exception:
                    sheets = None  # 非 xlsx 或解析失败时不展示 sheet 数

            # ---- 台账结构化字段（统一出口计算，不改动任何 parser）----
            rec_country = tool.get("country", "通用")
            rec_count = _parse_count(info) if info else None
            rec_gross = None
            if out_b64:
                try:
                    rec_gross = compute_gross_from_xlsx(out_b64)
                except Exception:
                    rec_gross = None
            rec_month = _parse_month(filename)

            resp = {"ok": True, "filename": out_name, "data": out_b64,
                    "meta": {"elapsed_ms": elapsed_ms, "in_bytes": in_bytes,
                             "out_bytes": out_bytes, "sheets": sheets},
                    "country": rec_country, "count": rec_count,
                    "gross": rec_gross, "month": rec_month}
            if info is not None:
                resp["people"] = info
            self._send(200, json.dumps(resp))
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print("[ERROR] 工具处理异常:\n" + tb)
            self._send(200, json.dumps({"ok": False, "error": str(e), "traceback": tb}))

    # ---- 共享口令解锁 (轻量免登录网关) ----
    def serve_unlock(self):
        if not SHARE_PASSCODE:
            self._send(200, json.dumps({"ok": False, "error": "未启用共享口令模式"}))
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            pc = payload.get("passcode", "") or ""
        except Exception:
            self._send(200, json.dumps({"ok": False, "error": "请求格式错误"}))
            return
        if pc != SHARE_PASSCODE:
            self._send(200, json.dumps({"ok": False, "error": "口令错误"}))
            return
        sid = secrets.token_hex(16)
        SESSIONS[sid] = {
            "open_id": "share:" + sid[:8], "name": "共享用户",
            "tenant_key": "", "first_login": True, "login_at": int(time.time()),
            "ts": int(time.time()), "anon": True,
        }
        is_https = self._scheme_of() == "https"
        cookie = make_cookie("sid", sid, max_age=SESSION_TTL,
                             secure=is_https, same_site="None" if is_https else "Lax")
        self._send(200, json.dumps({"ok": True, "sid": sid, "user": {
            "open_id": "share:" + sid[:8], "name": "共享用户",
            "tenant_key": "", "first_login": True, "login_at": int(time.time()), "anon": True,
        }}), cookies=[cookie])

    # ---- 网页内修改共享口令（需先验证当前口令） ----
    def serve_change_passcode(self):
        global SHARE_PASSCODE
        if not SHARE_PASSCODE:
            self._send(200, json.dumps({"ok": False, "error": "未启用共享口令模式"}))
            return
        # 已登录用户（含共享用户/飞书用户）均可修改；当前口令必须正确
        cur = ""
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            cur = (payload.get("current", "") or "")
            new = (payload.get("new", "") or "")
        except Exception:
            self._send(200, json.dumps({"ok": False, "error": "请求格式错误"}))
            return
        if cur != SHARE_PASSCODE:
            self._send(200, json.dumps({"ok": False, "error": "当前口令不正确"}))
            return
        if len(new) < 4:
            self._send(200, json.dumps({"ok": False, "error": "新口令至少 4 位"}))
            return
        # 持久化到口令文件（下次启动仍生效）
        try:
            with open(PASSCODE_FILE, "w", encoding="utf-8") as _f:
                _f.write(new)
        except Exception as _e:
            dlog("写入口令文件失败: %s" % _e)
        SHARE_PASSCODE = new
        dlog("共享口令已被修改（网页内操作）")
        self._send(200, json.dumps({"ok": True}))

    # ---- 飞书登录入口 ----
    def serve_login(self):
        # 内网共享模式：redirect_uri 动态跟随访问地址（不再强制 localhost）。
        # 注意：飞书开放平台后台的「回调域名」白名单需包含当前访问地址
        # （如 http://<内网IP>:8765），否则飞书授权页会拒绝。
        state = secrets.token_hex(16)
        redir = self._dyn_redirect_uri()
        is_https = self._scheme_of() == "https"
        dlog("LOGIN host=%s xfwd=%s redirect_uri=%s is_https=%s state=%s" % (
            self.headers.get("Host"), self.headers.get("X-Forwarded-Host"), redir, is_https, state))
        # 同时写入 cookie(优先) 与内存兜底：部分浏览器/安全策略会阻止跨站 cookie,
        # 导致回调时读不到 oauth_state; 此时可用服务端 STATE_STORE 兜底校验
        cookie = make_cookie("oauth_state", state, max_age=300,
                             secure=is_https, same_site="None" if is_https else "Lax")
        client_ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        _store_state(state, client_ip, redir)
        params = urllib.parse.urlencode({
            "app_id": CFG["app_id"],
            "redirect_uri": redir,
            "state": state,
            "response_type": "code",
        })
        loc = CFG["authorize_url"] + "?" + params
        self._send(302, "", extra_headers={"Location": loc}, cookies=[cookie])

    # ---- 飞书回调 ----
    def serve_callback(self, query):
        qs = urllib.parse.parse_qs(query)
        code = qs.get("code", [""])[0]
        state = qs.get("state", [""])[0]
        expected = parse_cookies(self).get("oauth_state", "")

        # 1) 校验 state (防 CSRF)。优先用 cookie 校验；若浏览器未发送跨站 cookie,
        # 则回退到服务端内存 STATE_STORE 兜底校验
        client_ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        state_ok = bool(state and expected and state == expected)
        dlog("CALLBACK code=%s state=%s cookie_state=%s ip=%s cookie_ok=%s" % (
            bool(code), state[:8] if state else None, expected[:8] if expected else None, client_ip, state_ok))
        if not state_ok:
            state_ok = _check_state(state, client_ip)
            dlog("CALLBACK fallback_state_ok=%s" % state_ok)
        if not state_ok:
            self._send(400, simple_html("登录被拒绝", "state 校验失败，可能存在跨站请求伪造风险。请重新点击飞书登录。"),
                       ctype="text/html")
            return
        # 校验通过后清理该 state，防止重放
        STATE_STORE.pop(state, None)

        # 2) 用 code 换身份 (secret 仅在服务端使用)
        try:
            _tok, user = feishu_exchange_code(code)
            dlog("CALLBACK exchange_ok open_id=%s name=%s" % (user.get("open_id"), user.get("name")))
        except Exception as e:
            dlog("CALLBACK exchange_fail: %s" % e)
            self._send(200, simple_html("登录失败", str(e)), ctype="text/html")
            return

        open_id = user.get("open_id")
        if not open_id:
            dlog("CALLBACK no_open_id")
            self._send(200, simple_html("登录失败", "飞书未返回 open_id"), ctype="text/html")
            return

        # 3) 停用用户拦截
        if open_id in load_disabled():
            self._send(403, simple_html("账号已停用", "该飞书账号已被停用，无法登录。如需恢复请联系管理员。"),
                       ctype="text/html")
            return

        # 4) 首次登录识别 + tenant_key 回填
        known = load_known()
        first_login = open_id not in known
        if first_login:
            mark_known(open_id)
        tk = user.get("tenant_key")
        if tk and not CFG.get("tenant_key"):
            CFG["tenant_key"] = tk
            save_config(CFG)

        # 5) 写 session
        sid = secrets.token_hex(16)
        SESSIONS[sid] = {
            "open_id": open_id, "name": user.get("name"),
            "tenant_key": tk, "first_login": first_login,
            "ts": time.time(), "login_at": time.time(),
        }
        redir = self._dyn_redirect_uri()
        is_https = redir.startswith("https://")
        # 通过 https 隧道访问时为跨站场景: sid 也必须用 SameSite=None; Secure,
        # 否则部分浏览器在跨站回调后不发送该 cookie, 导致首页仍显示未登录
        # 同时把 sid 放进回跳 URL (?sid=...), 前端存入 localStorage 后用
        # Authorization: Bearer 头携带, 彻底绕开跨站 cookie 被浏览器阻止的问题
        # 回跳用绝对 URL (基于真实 Host), 避免某些代理/隧道对相对 302 处理有歧义
        host = self.headers.get("Host", "localhost:8765")
        scheme = "https" if is_https else "http"
        loc = "%s://%s/?sid=%s" % (scheme, host, sid)
        self._send(302, "", extra_headers={"Location": loc},
                   cookies=[make_cookie("sid", sid, max_age=SESSION_TTL,
                                       secure=is_https,
                                       same_site="None" if is_https else "Lax"),
                            clear_cookie("oauth_state", secure=is_https,
                                         same_site="None" if is_https else "Lax")])
        dlog("CALLBACK redirect %s open_id=%s is_https=%s" % (loc, open_id, is_https))

    def serve_logout(self):
        sid = parse_cookies(self).get("sid")
        if sid and sid in SESSIONS:
            SESSIONS.pop(sid, None)
        self._send(302, "", extra_headers={"Location": "/"}, cookies=[clear_cookie("sid")])

    def log_message(self, *args):
        pass  # 静默日志


# ---------------------------------------------------------------------------
# 端口选择 (占用自动顺延) + 启动
# ---------------------------------------------------------------------------
def find_free_port(host, start, span):
    for p in range(start, start + span + 1):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((host, p))
            s.close()
            return p
        except OSError:
            continue
    raise RuntimeError("在 %d~%d 找不到可用端口" % (start, start + span))


def main():
    port = find_free_port(HOST, PORT, PORT_SPAN)
    server = ThreadingHTTPServer((HOST, port), Handler)
    local_url = "http://localhost:%d/" % port

    port_file = os.path.join(_BASE, ".web_port")
    try:
        with open(port_file, "w", encoding="utf-8") as f:
            f.write(str(port))
    except Exception:
        pass

    print("[WEB] 办公工具集成平台已启动: http://0.0.0.0:%d/  (本机打开: %s)" % (port, local_url))
    if SHARE_PASSCODE:
        print("[WEB] 登录方式：共享口令（默认）: %s  —— 同事首次进入请输入此口令；可在网页右上角「修改口令」更改" % SHARE_PASSCODE)
    print("[WEB] 正在打开浏览器… (关闭请按 Ctrl+C)")
    try:
        webbrowser.open(local_url)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[WEB] 服务已停止。")
    finally:
        try:
            if os.path.exists(port_file):
                os.remove(port_file)
        except Exception:
            pass


if __name__ == "__main__":
    main()
