#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
波兰工资考勤工具箱 —— 海外薪资工作台 适配层
=======================================================================
把「波兰工资考勤工具箱 (Windows 便携版 v1.0)」的 10 个工具整合进网页工作台。

设计原则（重要，后续维护请遵守）
-----------------------------------------------------------------------
1. 工具源码【原样】放在 ./poland_tools/NN_xxx/ 下，本文件不改动它们的任何解析逻辑。
   升级某个工具 = 用新的 .py 覆盖同名文件，重启工作台即生效（与工具箱使用说明一致）。
2. 本文件只做四件事：
     (a) 给 tkinter / flask 打「无头桩」，让纯 GUI 工具能在服务端被调用；
     (b) 把网页传来的字节流落地成临时文件、把工具产物收回成字节流；
     (c) 需要一次处理多个文件时打包 zip；
     (d) 尽量复用工具【原有的】方法（如 02 的 _auto_load_excel/_encrypt_worker、
         03 的 load_excel/_match_pdf、04 的 parse_keywords/process_single_pdf），
         只补它们依赖的界面属性 —— 避免复制粘贴导致逻辑漂移。
3. 任何一路文件失败都要在结果里逐条说明，绝不静默丢弃。

临时文件目录每次请求独立创建并清理；源文件全程只读。
"""

import base64
import io
import os
import re
import shutil
import sys
import tempfile
import types
import zipfile

# ===========================================================================
# 一、GUI / Web 依赖「无头桩」
# ===========================================================================

_STUBS_DONE = False
# 桩模块记录到的对话框文案（工具内部弹窗会落到这里，便于回传给用户看）
DIALOG_LOG = []
# 进度回调里抛出的异常单独记（工具在子线程里刷 UI，回调报错不代表处理失败，
# 不能混进 DIALOG_LOG 变成用户可见的弹窗文案）
AFTER_ERRORS = []


class _Stub(object):
    """万能桩：可被继承(tk.Tk)、可被调用(返回自身)、可当容器/装饰器。

    * class App(tk.Tk)      -> _Stub 是类，可继承
    * tk.StringVar()        -> _Stub 实例
    * @app.route('/')       -> _Stub.__call__(单个可调用对象) 原样返回被装饰函数，
                              不会把路由函数变成桩，避免误伤 Flask 工具的核心代码
    * stub["maximum"] = 5   -> __setitem__ 吞掉
    """

    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        # 装饰器用法：@deco 或 @deco(...) 之后再套函数，都原样放行
        if len(a) == 1 and not k and (callable(a[0]) or isinstance(a[0], type)):
            return a[0]
        return self

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _Stub()

    def __getitem__(self, k):
        return _Stub()

    def __setitem__(self, k, v):
        return None

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return True

    def __repr__(self):
        return "<stub>"


class _ShimVar(object):
    """替代 tk.StringVar / BooleanVar / IntVar。"""

    def __init__(self, value=""):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v

    def __str__(self):
        return str(self._v)


class _ShimCtl(object):
    """替代 tk.Label / ttk.Progressbar / Text 等控件（只接住 config/set 等调用）。"""

    def __init__(self, **kw):
        self.kw = dict(kw)

    def config(self, **kw):
        self.kw.update(kw)

    configure = config

    def __setitem__(self, k, v):
        self.kw[k] = v

    def __getitem__(self, k):
        return self.kw.get(k)

    def insert(self, *a, **k):
        return None

    def delete(self, *a, **k):
        return None

    def see(self, *a, **k):
        return None

    def update_idletasks(self):
        return None

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _noop


def _noop(*a, **k):
    return None


class _ShimRoot(object):
    """替代 Tk 根窗口：把 after(0, fn) 立即执行（工具靠它做进度回调），
    使原本在子线程里跑的 worker 变成同步执行。"""

    def __init__(self):
        self._n = 0

    def after(self, ms=0, fn=None, *a):
        if callable(fn):
            try:
                fn(*a)
            except Exception as e:
                AFTER_ERRORS.append("[回调异常] %s" % e)
        return None

    def after_idle(self, fn=None, *a):
        return self.after(0, fn, *a)

    def after_cancel(self, *a, **k):
        return None

    def title(self, *a, **k):
        return None

    def geometry(self, *a, **k):
        return None

    def minsize(self, *a, **k):
        return None

    def resizable(self, *a, **k):
        return None

    def update(self):
        return None

    def destroy(self):
        return None

    def tk(self, *a, **k):
        return _Stub()

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _noop


class _MessageBoxStub(object):
    """messagebox 桩：一律不确认（ask* 返回 False），文案记入 DIALOG_LOG。

    这样即使某条代码路径意外走到「请确认」对话框，也不会静默替用户点「是」。
    """

    @staticmethod
    def _rec(title, message, *a, **k):
        DIALOG_LOG.append("[%s] %s" % (title, message))

    def showinfo(self, title=None, message=None, *a, **k):
        self._rec(title, message)
        return "ok"

    def showwarning(self, title=None, message=None, *a, **k):
        self._rec(title, message)
        return "ok"

    def showerror(self, title=None, message=None, *a, **k):
        self._rec(title, message)
        return "ok"

    def askyesno(self, title=None, message=None, *a, **k):
        self._rec(title, message)
        return False

    def askokcancel(self, title=None, message=None, *a, **k):
        self._rec(title, message)
        return False

    def askquestion(self, title=None, message=None, *a, **k):
        self._rec(title, message)
        return "no"

    def askretrycancel(self, title=None, message=None, *a, **k):
        self._rec(title, message)
        return False


class _FileDialogStub(object):
    """filedialog 桩：没有界面可选文件，一律返回空（调用方会自然跳过）。"""

    @staticmethod
    def askopenfilename(*a, **k):
        return ""

    @staticmethod
    def askopenfilenames(*a, **k):
        return ()

    @staticmethod
    def askdirectory(*a, **k):
        return ""

    @staticmethod
    def asksaveasfilename(*a, **k):
        return ""

    @staticmethod
    def askstring(*a, **k):
        return None


def _mk_stub_module(name, overrides=None):
    m = types.ModuleType(name)
    m.__path__ = []                      # 伪装成包，允许 import tkinter.ttk
    m.__getattr__ = lambda attr: _Stub   # PEP 562：缺失属性返回「类」，可继承可调用
    for k, v in (overrides or {}).items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _install_gui_stubs():
    """在加载任何 GUI 工具模块之前，把 tkinter / tkinterdnd2 / flask 换成无头桩。

    必须【无条件】安装（即使本机真的装了 tkinter），理由：
      1) dev 环境与打包后的 exe 行为完全一致，验证结果可直接复用；
      2) PyInstaller 不必再打包 Tcl/Tk（约 10MB）与 Flask；
      3) 避免任何工具路径意外创建真实窗口。
    调试需要真 tkinter 时设环境变量 POLAND_REAL_TK=1。
    """
    global _STUBS_DONE
    if _STUBS_DONE:
        return
    _STUBS_DONE = True
    if os.environ.get("POLAND_REAL_TK") == "1":
        return

    mb = _mk_stub_module("tkinter.messagebox", {"__all__": []})
    for nm in ("showinfo", "showwarning", "showerror", "askyesno",
               "askokcancel", "askquestion", "askretrycancel"):
        setattr(mb, nm, getattr(_MessageBoxStub, nm))

    fd = _mk_stub_module("tkinter.filedialog")
    for nm in ("askopenfilename", "askopenfilenames", "askdirectory",
               "asksaveasfilename", "askstring"):
        setattr(fd, nm, staticmethod(getattr(_FileDialogStub, nm)).__func__)

    ttk = _mk_stub_module("tkinter.ttk")
    scrolled = _mk_stub_module("tkinter.scrolledtext")
    _mk_stub_module("tkinter.simpledialog")
    _mk_stub_module("tkinter.colorchooser")
    _mk_stub_module("tkinter.font")

    tk = _mk_stub_module("tkinter", {
        "ttk": ttk, "filedialog": fd, "messagebox": mb,
        "scrolledtext": scrolled,
    })
    _mk_stub_module("tkinterdnd2", {"TkinterDnD": _Stub, "DND_FILES": "DND_Files"})
    _mk_stub_module("flask", {"Flask": _Stub, "request": _Stub, "jsonify": _Stub,
                              "send_file": _Stub, "render_template": _Stub,
                              "render_template_string": _Stub, "Response": _Stub,
                              "make_response": _Stub, "redirect": _Stub, "url_for": _Stub})

    # 保证 `import tkinter as tk` 与 `from tkinter import ttk` 都拿到同一批桩
    sys.modules["tkinter"] = tk
    assert sys.modules["tkinter.ttk"] is ttk


# ===========================================================================
# 二、poland_tools 目录定位（支持「exe 同级目录覆盖」式原地升级）
# ===========================================================================

_HERE = os.path.dirname(os.path.abspath(__file__))


def _candidate_roots():
    cands = []
    env = os.environ.get("POLAND_TOOLS_DIR", "").strip()
    if env:
        cands.append(env)
    if getattr(sys, "frozen", False):
        # 打包态：优先用 exe 同级目录下的 poland_tools（用户可直接覆盖升级）
        cands.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "poland_tools"))
    cands.append(os.path.join(_HERE, "poland_tools"))
    mp = getattr(sys, "_MEIPASS", None)
    if mp:
        cands.append(os.path.join(mp, "poland_tools"))
    out, seen = [], set()
    for c in cands:
        c = os.path.abspath(c)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def resolve(rel_path):
    """按候选根顺序找第一个存在的文件 —— 支持「只覆盖其中几个工具」的部分升级。"""
    rel_path = rel_path.replace("/", os.sep)
    for root in _candidate_roots():
        p = os.path.join(root, rel_path)
        if os.path.isfile(p):
            return p
    raise IOError("未找到波兰工具源文件: %s（已尝试 %s）" % (rel_path, _candidate_roots()))


def tools_root():
    for root in _candidate_roots():
        if os.path.isdir(root):
            return root
    return _candidate_roots()[-1]


# ===========================================================================
# 三、工具模块加载（唯一模块名，避免 03/08 同名 pdf_renamer 互相覆盖）
# ===========================================================================

_LOADED = {}


def _load(key, rel_path):
    if key in _LOADED:
        return _LOADED[key]
    _install_gui_stubs()
    path = resolve(rel_path)
    mod_name = "pl_tool_" + key
    import importlib.util
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise IOError("无法加载模块: %s" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod       # 便于 dataclass / 自引用 / traceback 定位
    spec.loader.exec_module(mod)
    _LOADED[key] = mod
    return mod


def loaded_report():
    """自检用：返回各工具源文件实际生效路径。"""
    out = []
    for key, rel, label in TOOL_FILES:
        try:
            out.append("%-16s %s" % (label, resolve(rel)))
        except Exception as e:
            out.append("%-16s !! %s" % (label, e))
    return out


# (模块 key, 相对路径, 展示名)
TOOL_FILES = [
    ("01_pesel",    "01_pesel/pesel_tool.py",                     "PESEL信息提取"),
    ("02_encrypt",  "02_encrypt/pdf_encryptor.py",                "PDF批量加密"),
    ("03_rename",   "03_rename/pdf_renamer.py",                   "PDF重命名"),
    ("04_sanitize", "04_sanitize/pdf_sanitizer.py",               "PDF隐私脱敏"),
    ("05_payroll",  "05_payroll/pdf_payroll_extractor.py",         "波兰工资单提取"),
    ("06_merge",    "06_attendance/merge_all.py",                 "波兰考勤合并"),
    ("07_p45",      "07_p45/p45_tool.py",                         "P45处理"),
    ("08_pension",  "08_pension_rename/pdf_renamer.py",           "养老金信函重命名"),
    ("09_irish",    "09_irish/irish_payslip_tool.py",             "爱尔兰工资单"),
    ("10_german",   "10_german/lohnjournal_extractor.py",         "德国工资单提取"),
]


# ===========================================================================
# 四、通用工具函数
# ===========================================================================

def _b64(b):
    return base64.b64encode(b).decode("ascii")


def _basename(name):
    return os.path.basename((name or "").replace("\\", "/")) or "input.bin"


def _ext(name):
    return os.path.splitext(_basename(name))[1].lower()


def _pick(files, exts):
    """按扩展名挑出文件，保持上传顺序。"""
    return [(nm, data) for nm, data in files if _ext(nm) in exts]


def _safe(name, fallback="file"):
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", _basename(name)).strip(" .")
    return n or fallback


def _unique_name(name, used):
    """同名去重：a.pdf / a_1.pdf / a_2.pdf（与 03 execute_rename 的策略一致）。"""
    if name not in used:
        used.add(name)
        return name
    base, ext = os.path.splitext(name)
    i = 1
    while ("%s_%d%s" % (base, i, ext)) in used:
        i += 1
    out = "%s_%d%s" % (base, i, ext)
    used.add(out)
    return out


def _zip_bytes(items):
    """items: [(arcname, bytes)] -> zip 字节。"""
    buf = io.BytesIO()
    used = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nm, b in items:
            z.writestr(_unique_name(_safe(nm), used), b)
    return buf.getvalue()


def _emit(items, info, zip_stem, ext=".zip"):
    """统一出口：1 个产物直接给原文件，多个产物打包 zip。"""
    items = [(n, b) for n, b in items if b is not None]
    if not items:
        return None
    if len(items) == 1:
        return (items[0][0], _b64(items[0][1]), info)
    return (zip_stem + ext, _b64(_zip_bytes(items)), info)


def _reset_dialogs():
    del DIALOG_LOG[:]


def _dialog_text():
    return " ｜ ".join(DIALOG_LOG) if DIALOG_LOG else ""


def _fail(reason):
    return (None, None, reason)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 上传件类型自识别（用户上传了「另一种文档」时说清楚它是什么、该用哪个工具）
# ---------------------------------------------------------------------------

def _pdf_text_head(data, pages=2):
    """取 PDF 前 N 页文本；拿不到（扫描件/坏文件）返回空串，绝不抛异常。"""
    try:
        import fitz
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            n = min(pages, len(doc))
            return "\n".join(doc[i].get_text() for i in range(n))
        finally:
            doc.close()
    except Exception:
        return ""


# 判定顺序有讲究：先认「表格类」（P45/Lohnjournal），再认「工资单类」，最后才是 PESEL 类，
# 否则一张含 PESEL 的工资单会被误判成 PESEL 表单。
_DOC_RULES = [
    ("英国 P45 表格", "英国 P45 处理（重命名+加密）",
     lambda t: ("p45" in t) or ("ni number" in t and ("leaving date" in t or "leaving the employment" in t))),
    ("英国养老金自动入职信（AE Job Holder Letter）", "英国养老金信函重命名",
     lambda t: ("pensions regulator" in t) or ("job holder" in t)
               or ("dear" in t and ("eligible" in t or "enrol" in t))),
    ("德国 Lohnjournal 工资单", "德国工资单提取（Lohnjournal）",
     lambda t: ("lohnjournal" in t) or ("pers.-nr" in t) or ("st.kl" in t and "lohnsteuer" in t)),
    ("爱尔兰工资单", "爱尔兰工资单处理",
     lambda t: ("pps number" in t) or ("pps" in t and ("payslip" in t or "ireland" in t))),
    ("波兰多人工资明细表（Wyciąg）", "波兰工资单提取",
     lambda t: ("pracownik [akronim]" in t) or ("el. wyp" in t) or ("stawka **" in t)),
    ("波兰单人工资单（Kwitek wypłaty）", "波兰工资单提取",
     lambda t: ("kwitek" in t) or ("pracownik:" in t and ("stawka" in t or "wynagrodzenie" in t))),
    ("波兰证件/表单（含 PESEL）", "波兰 PESEL 信息提取",
     lambda t: "pesel" in t),
]


def _sniff_doc(data):
    """识别上传 PDF 的文档类型。返回 (类型标签, 建议工具名)；判断不了返回 ("", "")。"""
    if not data or data[:5] != b"%PDF-":
        return "", ""
    text = _pdf_text_head(data)
    if len(text.strip()) < 30:
        return "无文本层（疑似扫描件 / 图片型 PDF）", ""
    t = text.lower()
    for label, tool, hit in _DOC_RULES:
        try:
            if hit(t):
                return label, tool
        except Exception:
            continue
    return "", ""


def _doc_note(data, own_name=""):
    """给失败原因补一句「这是哪种文档 → 建议改用哪个工具」。识别不出返回空串。"""
    label, tool = _sniff_doc(data)
    if not label:
        return ""
    msg = "文档类型识别：%s。" % label
    if tool and tool != own_name:
        msg += "本文件更适合【%s】，建议改用该工具；" % tool
    return msg + "若确认要用本工具，请按下面「本工具期望格式」核对排版。"


# 单张工资单（Kwitek wypłaty）标签锚点兜底：
# 05 的正式解析依赖左侧 LP 序号列（x<140 且 y>80），单人工资单没有 LP 列、姓名在页眉，
# 所以正常路径必然 0 人。这里按标签取同行/相邻行的值，字段与 05 的 Excel 完全一致。
def _kwitek_worker(m, pdf_path):
    """从单人工资单 PDF 兜底提取 1 名员工；不像工资单则返回 None。"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
    except Exception:
        return None
    spans = []
    try:
        for page in doc:
            for b in page.get_text("dict").get("blocks", []):
                for line in b.get("lines", []):
                    for sp in line.get("spans", []):
                        if sp["text"].strip():
                            spans.append({"x": sp["bbox"][0], "y": sp["bbox"][1],
                                          "x1": sp["bbox"][2], "text": sp["text"]})
    finally:
        doc.close()
    if not spans:
        return None
    spans.sort(key=lambda s: (s["y"], s["x"]))
    rows = m.group_into_rows(spans)
    texts = [m.row_text(r) for r in rows]
    full = "\n".join(texts)

    w = m.new_worker("1")

    # 姓名：Pracownik: ZIEMIĘCKI SEBASTIAN [ZIEMIĘCKI_SEBASTIAN]
    mm = re.search(r"Pracownik:\s*([^\[\]\n]+?)\s*\[", full) or re.search(r"Pracownik:\s*([^\[\]\n]+)", full)
    if mm:
        w["name"] = re.sub(r"\s+", " ", mm.group(1)).strip(" -_")

    # 基本工资：Stawka: 5 500,00 PLN / mies.（值可能落在相邻的一行）
    for i, t in enumerate(texts):
        if "Stawka" in t:
            s = t if re.search(r"\d[\d\s\u00a0]*,\d{2}\s*PLN", t) else (
                t + " " + texts[i + 1] if i + 1 < len(texts) else t)
            mv = re.search(r"(\d[\d\s\u00a0]*,\d{2})\s*PLN", s)
            if mv:
                w["salary"] = int(float(mv.group(1).replace(" ", "").replace("\u00a0", "").replace(",", ".")))
            break

    # 工时：Czas pracy (N/P): 160:00 / 176:30
    mh = re.search(r"Czas pracy[^\n]*?(\d{1,3}:\d{2})\s*/\s*(\d{1,3}:\d{2})", full)
    if mh:
        w["standard_hours"], w["total_hours"] = mh.group(1), mh.group(2)
    else:
        mh = re.search(r"Czas pracy[^\n]*?(\d{1,3}:\d{2})", full)
        if mh:
            w["standard_hours"] = mh.group(1)

    # 双栏版面：左侧「缺勤」栏（标签 x≈47）与右侧「加班」栏（标签 x≈153）处在同一视觉行。
    # 不能用「标签所在的行」取值：05 的 group_into_rows 会把同一视觉行的 span 拆到不同行
    # （真实事故：Urlopy 的 "2 / 2"、Nadgodziny 50 的 "07:00" 都不在标签那一行里）。
    # 改为「在所有 span 里按标签 y 开窗，取右侧连续的数值簇」。
    def _pick_after(lab):
        x0 = lab["x1"] + 1.0
        picked, prev = [], None
        cands = [s for s in spans if s["x"] >= x0 and abs(s["y"] - lab["y"]) <= 4.0]
        for s in sorted(cands, key=lambda s: (s["x"], s["y"])):
            if prev is not None and (s["x"] - prev) > 8.0:   # 数值簇结束（跨栏了）
                break
            if not picked and not re.search(r"\d", s["text"]):
                continue
            picked.append(s)
            prev = s["x1"]
        return "".join(s["text"] for s in picked)

    def _label_span(pat):
        rx = re.compile(pat, re.I)
        for s in spans:                    # spans 已按 (y, x) 排序 → 取最上面的同名标签
            if rx.search(s["text"].strip()):
                return s
        return None

    # Urlopy / ZUS / NN / Inne / Nadg.50 / Nadg.100 / Nocne
    # （单人工资单的加班标签写作 Nadgodziny 50: / Nadgodziny 100:）
    for pat, key, is_time in ((r"^Urlopy\b", "urlopy", False),
                              (r"^ZUS\b", "zus", False),
                              (r"^NN\b", "nn", False),
                              (r"^Inne\b", "inne", False),
                              (r"^Nadg\.?\s*50\b|^Nadgodziny\s*50\b", "nadg50", True),
                              (r"^Nadg\.?\s*100\b|^Nadgodziny\s*100\b", "nadg100", True),
                              (r"^Nocne\b", "nocne", True)):
        lab = _label_span(pat)
        if lab is None:
            continue
        raw = _pick_after(lab)
        if is_time:
            mt = re.search(r"\d{1,3}:\d{2}", raw)
            if mt:
                w[key] = mt.group(0)
        else:
            val = re.sub(r"/+", "/", re.sub(r"[^\d/]", "", raw))
            if val:
                w[key] = val

    filled = sum(1 for k in ("salary", "standard_hours", "total_hours", "urlopy",
                             "zus", "nn", "inne", "nadg50", "nadg100", "nocne") if w[k])
    if not w["name"] or filled < 2:   # 姓名 + 至少 2 个数值字段，才算真的认出来了
        return None
    return w


# 08 信函姓名是按版面坐标猜的：遇到非信函文档会把页眉机构名当姓名
# （真实事故：【Oddział NFZ_ _ 1 1】）。宁可判不可信、保留原名，也不给出错误姓名。
_NAME_STOPWORDS = {
    "oddzial", "nfz", "zus", "pracodawca", "pracownik", "wyplata", "wynagrodzenie",
    "kwitek", "lista", "placy", "firma", "spolka", "sp", "spzoo", "sa", "bank",
    "adres", "nip", "regon", "pesel", "data", "okres", "netto", "brutto",
    "podstawa", "ubezpieczenie", "the", "pensions", "regulator", "dear",
    "employer", "employee", "eligible", "job", "holder", "letter", "ae",
    "ltd", "limited", "poland", "polska", "sir", "madam", "or", "and", "to", "your",
}
_NAME_TOKEN_OK = re.compile(r"^[A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f'\u2019.\-]{1,29}$")


def _plausible_person_name(name):
    """判断提取到的「姓名」是否像人名。返回 (是否可信, 原因)。"""
    if not name or not str(name).strip():
        return False, "未提取到姓名"
    n = re.sub(r"\s+", " ", str(name)).strip(" .,;:_-")
    if len(n) < 4 or len(n) > 60:
        return False, "长度异常"
    if re.search(r"\d", n) or re.search(r"[_\[\]{}()/\\|@#*+=]", n):
        return False, "含数字或符号（不像人名）"
    toks = [t for t in n.split(" ") if t]
    if not (1 < len(toks) <= 4):
        return False, "词数异常（%d 个词）" % len(toks)
    for t in toks:
        if t.rstrip(".").lower() in _NAME_STOPWORDS:
            return False, "含机构/字段词「%s」" % t
        if not _NAME_TOKEN_OK.match(t):
            return False, "含非姓名字符「%s」" % t
    return True, ""


# 把 07 的英文报错翻成中文（用户看到的是自己的输入，不该猜英文）
_P45_FIELD_CN = {"surname": "姓", "last_name": "姓", "first_name": "名", "forename": "名",
                 "name": "姓名", "leaving_date": "离职日期", "leave_date": "离职日期",
                 "ni_number": "NI Number", "nino": "NI Number"}


def _humanize_p45_error(msg):
    raw = (msg or "").strip()
    m = re.search(r"Missing fields?:\s*(.+)$", raw, re.I)
    if m:
        fields = [f.strip() for f in re.split(r"[,;，、]\s*", m.group(1)) if f.strip()]
        cn = "、".join(_P45_FIELD_CN.get(f.lower(), f) for f in fields)
        return "PDF 中未找到必需字段：%s（说明这不是可识别的 P45 表格）" % cn
    return raw or "未生成新文件"


# ===========================================================================
# 五、10 个工具的适配实现
#     统一签名: core(files, opt) -> (out_name, out_b64, info) 或 None/(None,None,原因)
#     files = [(文件名, bytes), ...]   opt = {extra...}
# ===========================================================================

# ---------------------------------------------------------------- 01 PESEL ---

PESEL_HEADERS = ["序号", "文件名", "PESEL", "是否找到", "校验位", "说明"]


def core_pesel(files, opt=None):
    m = _load("01_pesel", "01_pesel/pesel_tool.py")
    pdfs = _pick(files, {".pdf"})
    if not pdfs:
        return _fail("未收到 PDF 文件。本工具需要包含 PESEL 的 PDF（工资单/合同/表单）。")

    rows, ok_n, bad_n = [], 0, 0
    for i, (nm, data) in enumerate(pdfs, 1):
        base = _basename(nm)
        note = ""
        try:
            text = m.extract_text_from_pdf(io.BytesIO(data)) or ""
        except Exception as e:
            rows.append((i, base, "", "否", "-", "读取失败: %s" % e))
            bad_n += 1
            continue
        pesel = ""
        try:
            pesel = m.extract_pesel_from_text(text) or ""
        except Exception as e:
            note = "提取异常: %s" % e
        if not pesel:
            dn = _doc_note(data, "波兰 PESEL 信息提取")
            rows.append((i, base, "", "否", "-",
                         (note or "PDF 文本中未定位到 PESEL（可能为扫描件）") + (("；" + dn) if dn else "")))
            bad_n += 1
            continue
        try:
            valid = bool(m.validate_pesel(pesel))
        except Exception:
            valid = False
        rows.append((i, base, pesel, "是", "通过" if valid else "不通过",
                     note or ("" if valid else "校验位不通过，请人工复核该号码")))
        if valid:
            ok_n += 1
        else:
            bad_n += 1

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "PESEL提取"
    ws.append(PESEL_HEADERS)
    for c in range(1, len(PESEL_HEADERS) + 1):
        cell = ws.cell(1, c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4472C4")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r in rows:
        ws.append(list(r))
    ws.freeze_panes = "A2"
    for i, w in enumerate([6, 46, 16, 10, 10, 44], 1):
        ws.column_dimensions[chr(64 + i)].width = w
    out = io.BytesIO()
    wb.save(out)

    info = "共 %d 个文件 · 找到 PESEL %d 个 · 未找到 %d 个" % (len(pdfs), ok_n, bad_n)
    return _emit([("PESEL提取结果.xlsx", out.getvalue())], info, "PESEL提取结果")


# ------------------------------------------------------- 02 PDF/Excel 加密 ---

def core_encrypt(files, opt=None):
    m = _load("02_encrypt", "02_encrypt/pdf_encryptor.py")
    maps = _pick(files, {".xlsx", ".xls"})
    if not maps:
        return _fail("未收到「文件名 → 密码」Excel 密码表（.xlsx/.xls）。"
                     "请把密码表和要加密的文件一起拖进来。")
    map_name = _basename(maps[0][0])
    targets = [(nm, d) for nm, d in files
               if _ext(nm) in getattr(m, "SUPPORTED_EXTS", {".pdf", ".xlsx", ".xls"})
               and not (nm is maps[0][0] or _basename(nm) == map_name)]
    if not targets:
        return _fail("未收到要加密的文件（仅支持 PDF / xlsx / xls）。当前只有密码表: %s" % map_name)

    wd = tempfile.mkdtemp(prefix="pl_enc_")
    try:
        in_dir, out_dir = os.path.join(wd, "in"), os.path.join(wd, "out")
        os.makedirs(in_dir)
        os.makedirs(out_dir)
        map_path = os.path.join(wd, "pwd_" + _safe(map_name))
        with open(map_path, "wb") as f:
            f.write(maps[0][1])
        paths = []
        for nm, data in targets:
            p = os.path.join(in_dir, _safe(nm))
            with open(p, "wb") as f:
                f.write(data)
            paths.append(p)

        # 复用工具原方法：__new__ 绕过 GUI 初始化，只补它真正用到的界面属性
        app = m.FileEncryptorApp.__new__(m.FileEncryptorApp)
        app.root = _ShimRoot()
        app.excel_path = _ShimVar(map_path)
        app.excel_status_label = _ShimCtl()
        app.status_bar = _ShimCtl()
        app.progress = _ShimCtl()
        app.progress_label = _ShimCtl()
        app.output_dir = _ShimVar(out_dir)
        app.password_map = {}
        app.excel_row_count = 0
        app.file_items = []
        app._refresh_tree = _noop
        app._update_tree_row = _noop
        app._set_buttons_state = _noop
        app._recursive_set_buttons = _noop
        # 配色常量在 _build_ui 里定义（__new__ 已跳过），补齐以免 AttributeError
        for _cn, _cv in (("COLOR_OK", "#27ae60"), ("COLOR_WARN", "#e67e22"),
                         ("COLOR_ERR", "#e74c3c"), ("COLOR_BG", "#f5f6fa"),
                         ("COLOR_DROP", "#eef1f8"), ("COLOR_DROP_HOVER", "#e2e8f5"),
                         ("COLOR_ACCENT", "#3b6fd4")):
            if not hasattr(m.FileEncryptorApp, _cn):
                setattr(app, _cn, _cv)

        _reset_dialogs()
        app._auto_load_excel()                     # 原逻辑：自动识别表头列
        if not app.password_map:
            return _fail("密码表解析后为空：请确认列内含「文件名」列与「PESEL/密码」列。表头: %s" % map_name)
        app._add_files(paths)                      # 原逻辑：按文件名/主名匹配密码
        matched = [it for it in app.file_items if it.get("matched")]
        unmatched = [it for it in app.file_items if not it.get("matched")]
        if not matched:
            return _fail("没有任何文件在密码表里匹配到密码，请核对文件名是否与密码表一致。")

        app._encrypt_worker(matched, out_dir)      # 原逻辑：加密 + 失败不中断

        produced, failed = [], []
        for it in matched:
            src = os.path.join(out_dir, it["name"])
            if not it.get("result", "").startswith("✓") or not os.path.isfile(src):
                failed.append("%s（%s）" % (it["name"], it.get("result") or "未知原因"))
                continue
            if it["name"].lower().endswith(".xls"):
                src = os.path.splitext(src)[0] + ".xlsx"
            if os.path.isfile(src):
                produced.append((os.path.basename(src), _read(src)))
            else:
                failed.append("%s（输出文件未生成）" % it["name"])

        notes = []
        if unmatched:
            notes.append("未匹配密码被跳过: " + ", ".join(x["name"] for x in unmatched))
        if failed:
            notes.append("失败: " + "；".join(failed))
        if _dialog_text():
            notes.append(_dialog_text())
        info = "加密成功 %d 个 / 收到 %d 个%s" % (
            len(produced), len(targets), ("　" + "　".join(notes)) if notes else "")
        if not produced:
            return _fail("全部文件加密失败。" + ("　".join(notes) if notes else ""))
        return _emit(produced, info, "加密输出")
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ------------------------------------------------------ 03 PDF 按工号重命名 ---

def core_rename(files, opt=None):
    m = _load("03_rename", "03_rename/pdf_renamer.py")
    maps = _pick(files, {".xlsx", ".xls"})
    pdfs = _pick(files, {".pdf"})
    if not maps:
        return _fail("未收到「文件名称 → 工号」映射表（.xlsx/.xls）。")
    if not pdfs:
        return _fail("未收到需要重命名的 PDF 文件。")

    wd = tempfile.mkdtemp(prefix="pl_ren_")
    try:
        app = m.PDFRenamerApp.__new__(m.PDFRenamerApp)
        app.root = _ShimRoot()
        app.excel_path = _ShimVar("")
        app.sheet_var = _ShimVar("")
        app.name_col_var = _ShimVar("")
        app.id_col_var = _ShimVar("")
        app.match_mode_var = _ShimVar("精确匹配")
        app.keep_ext_var = _ShimVar(True)
        app.sheet_combo = _ShimCtl()
        app.name_col_combo = _ShimCtl()
        app.id_col_combo = _ShimCtl()
        app.status_var = _ShimVar("")
        app.log_text = _ShimCtl()
        app.pdf_files = []
        app.excel_data = {}
        app.headers = []
        app.sheets = []
        app.preview_map = {}
        app.load_config = _noop      # 不读用户本机配置，避免影响结果
        app.save_config = _noop      # 不回写用户本机配置
        app.refresh_tree = _noop
        logs = []
        app.log = lambda msg: logs.append(str(msg))

        # 多张映射表（多站点）时逐张加载后合并，键为第一优先级
        combined, sheets_used = {}, []
        for nm, data in maps:
            p = os.path.join(wd, _safe(nm))
            with open(p, "wb") as f:
                f.write(data)
            app.excel_path.set(p)
            app.load_excel()
            sheets_used.append(_basename(nm))

            # load_excel 在识别不出列时会**静默**退回 headers[0]/headers[1]：
            # 拿 PESEL 提取结果表（序号/PDF 文件名/PESEL 号码/状态）当映射表时，
            # 「文件名称」和「工号」会双双落到同一列，产物变成 alpha.pdf.pdf 这种
            # 看着成功、其实全错的名字。宁可不做，也不能给错名字（避坑清单 §15.4）。
            tbl = _basename(nm)
            hdrs = [h for h in (app.headers or []) if h]
            id_hit = app._auto_detect_col(app.headers or [], m.ID_KEYWORDS) if hdrs else ""
            id_col, name_col = app.id_col_var.get(), app.name_col_var.get()
            if hdrs and not id_hit:
                return _fail("映射表「%s」里没有「工号」列（该表实际列：%s）。"
                             "按工号重命名需要一张同时含「文件名称」列与「工号」列的表，"
                             "例如：文件名称=张三的工资单.pdf、工号=A001。"
                             "注意 PESEL 提取结果表（序号/PDF 文件名/PESEL 号码/状态）里没有工号，"
                             "不能当映射表用。" % (tbl, "、".join(hdrs)))
            if hdrs and name_col and name_col == id_col:
                return _fail("映射表「%s」的「文件名称」列和「工号」列都指向了同一列「%s」"
                             "（该表实际列：%s），继续做会把文件名改成文件名的重复值。"
                             "请改用含「文件名称」列与「工号」列的映射表。"
                             % (tbl, name_col, "、".join(hdrs)))
            for k, v in (app.excel_data or {}).items():
                combined.setdefault(k, v)
        if not combined:
            return _fail("映射表未解析出任何有效行（需含「文件名称」列与「工号」列）。")

        # 重命名只改产物名，不动服务器上任何文件
        out, ok, miss, used = [], 0, [], set()
        for nm, data in pdfs:
            base = _basename(nm)
            emp, matched, msg = "", False, ""
            try:
                emp, matched, msg = app._match_pdf(base)
            except Exception as e:
                msg = "匹配异常: %s" % e
            if not matched:
                # 精确匹配没中，再按「包含匹配」重试一次（等同人工在界面上切换一次）
                app.match_mode_var.set("包含匹配")
                try:
                    emp2, matched2, msg2 = app._match_pdf(base)
                except Exception as e:
                    emp2, matched2, msg2 = "", False, "包含匹配异常: %s" % e
                finally:
                    app.match_mode_var.set("精确匹配")
                if matched2:
                    emp, matched, msg = emp2, True, msg2
            if matched and emp:
                new = "%s%s" % (emp, os.path.splitext(base)[1])
                out.append((_unique_name(_safe(new), used), data))
                ok += 1
            else:
                out.append((_unique_name(_safe(base), used), data))
                miss.append("%s（%s）" % (base, msg or "未找到匹配"))

        notes = []
        if miss:
            notes.append("未匹配 %d 个（保留原名）: %s" % (len(miss), "；".join(miss[:20])))
        if len(maps) > 1:
            notes.append("已合并 %d 张映射表: %s" % (len(maps), ", ".join(sheets_used)))
        info = "重命名 %d 个 / 共 %d 个 PDF%s" % (
            ok, len(pdfs), ("　" + "　".join(notes)) if notes else "")
        return _emit(out, info, "重命名输出")
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# -------------------------------------------------------- 04 PDF 隐私脱敏 ---

_DEFAULT_SANITIZE_KW = "Pracownik:\nData wystawienia:\npracownika\nPESEL:+11"


def core_sanitize(files, opt=None):
    m = _load("04_sanitize", "04_sanitize/pdf_sanitizer.py")
    pdfs = _pick(files, {".pdf"})
    if not pdfs:
        return _fail("未收到 PDF 文件。")

    raw_kw = None
    txts = _pick(files, {".txt"})
    kw_source = "工具内置默认关键词"
    if txts:
        for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
            try:
                raw_kw = txts[0][1].decode(enc)
                kw_source = "关键词文件 %s（%s）" % (_basename(txts[0][0]), enc)
                break
            except Exception:
                continue
    if not raw_kw:
        raw_kw = getattr(m, "DEFAULT_KEYWORDS", _DEFAULT_SANITIZE_KW)
    # 关键词一律传「行列表」：GUI 那边 get_keywords() 就是 splitlines 后的列表。
    # 注意 process_single_pdf 内部会自己调 self.parse_keywords(keywords)，
    # 所以这里必须传原始行列表，不能预先 parse 成 (line_kw, targeted_kw) 元组，
    # 否则它会去 match 列表对象，报 expected string or bytes-like object。
    if isinstance(raw_kw, str):
        kw_list = [ln.strip() for ln in raw_kw.splitlines() if ln.strip()]
    else:
        kw_list = [str(x).strip() for x in raw_kw if str(x).strip()]
    if not kw_list:
        return _fail("关键词为空，未执行脱敏。")

    dpi, margin = 200, 10        # 与工具界面默认值一致
    app = m.PDFSanitizerApp.__new__(m.PDFSanitizerApp)
    logs = []
    app.log = lambda msg: logs.append(str(msg))

    wd = tempfile.mkdtemp(prefix="pl_san_")
    try:
        in_dir, out_dir = os.path.join(wd, "in"), os.path.join(wd, "out")
        os.makedirs(in_dir)
        os.makedirs(out_dir)
        _reset_dialogs()
        produced, failed = [], []
        for nm, data in pdfs:
            base = _basename(nm)
            p = os.path.join(in_dir, _safe(base))
            with open(p, "wb") as f:
                f.write(data)
            try:
                outp = app.process_single_pdf(p, out_dir, kw_list, dpi, margin)
            except Exception as e:
                failed.append("%s（%s）" % (base, e))
                continue
            if outp and os.path.isfile(outp):
                produced.append((os.path.basename(outp), _read(outp)))
            else:
                failed.append("%s（未生成图片）" % base)

        notes = ["关键词来源: " + kw_source]
        if failed:
            notes.append("失败: " + "；".join(failed))
        if _dialog_text():
            notes.append(_dialog_text())
        if logs:
            notes.append("工具日志: " + "；".join(logs[-5:]))
        info = "已脱敏 %d 个 / 共 %d 个 PDF（%d dpi，留白 %d）%s" % (
            len(produced), len(pdfs), dpi, margin, "　" + "　".join(notes))
        if not produced:
            return _fail("全部文件脱敏失败。" + "　".join(notes))
        return _emit(produced, info, "脱敏输出")
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ---------------------------------------------------- 05 波兰工资单提取 ---

def core_payroll(files, opt=None):
    m = _load("05_payroll", "05_payroll/pdf_payroll_extractor.py")
    pdfs = _pick(files, {".pdf"})
    if not pdfs:
        return _fail("未收到 PDF 文件。本工具需文本型波兰工资单 PDF（多人明细表，或单人 Kwitek wypłaty）。")

    wd = tempfile.mkdtemp(prefix="pl_pay_")
    try:
        produced, failed, total_people, details = [], [], 0, []
        for nm, data in pdfs:
            base = _basename(nm)
            p = os.path.join(wd, _safe(base))
            with open(p, "wb") as f:
                f.write(data)
            err, how = "", ""
            try:
                workers = m.extract_workers(p)
            except Exception as e:
                workers, err = [], "解析异常: %s" % e
            if not workers:
                # 单人工资单（Kwitek wypłaty）没有 LP 序号列，正常路径必然 0 人 → 标签锚点兜底
                kw = _kwitek_worker(m, p)
                if kw:
                    workers, how = [kw], "（单人工资单兜底解析）"
            if not workers:
                dn = _doc_note(data, "波兰工资单提取")
                failed.append("%s（未解析到员工行%s%s）" % (
                    base, ("；" + err) if err else "", ("；" + dn) if dn else ""))
                continue
            outp = os.path.join(wd, os.path.splitext(_safe(base))[0] + ".xlsx")
            m.write_to_excel(workers, outp, base)
            if os.path.isfile(outp):
                produced.append((os.path.splitext(base)[0] + ".xlsx", _read(outp)))
                total_people += len(workers)
                details.append("%s: %d 人%s" % (base, len(workers), how))
            else:
                failed.append("%s（Excel 未生成）" % base)

        notes = []
        if details:
            notes.append("；".join(details))
        if failed:
            notes.append("失败: " + "；".join(failed))
        info = "%d 名员工（%d 个 PDF）%s" % (
            total_people, len(pdfs), "　" + "　".join(notes) if notes else "")
        if not produced:
            return _fail("未提取到任何员工数据。" + ("　".join(notes) if notes else ""))
        return _emit(produced, info, "波兰工资单提取")
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ------------------------------------------------------ 06 波兰考勤合并 ---

_TPL_PAT = re.compile(r"汇总字段|模板|表头|template", re.I)


def core_attendance(files, opt=None):
    sheets = _pick(files, {".xlsx", ".xlsm", ".xls"})
    if not sheets:
        return _fail("未收到考勤表 xlsx（可多个站点）。（如需生成 Report汇总(指定表头) 表，"
                     "再拖入文件名含「汇总字段」或「模板」的 xlsx）")
    tpl = [(nm, d) for nm, d in sheets if _TPL_PAT.search(_basename(nm))]
    src = [(nm, d) for nm, d in sheets if not _TPL_PAT.search(_basename(nm))]
    if not src:
        return _fail("只收到模板文件，没有考勤表。文件名含「汇总字段/模板/表头」的会被当作表头模板。")
    if not tpl:
        # 也接受「只有一个 xlsx 且不是考勤表」之外的情况：明确告知未启用 Report 表
        tpl = []

    wd = tempfile.mkdtemp(prefix="pl_att_")
    try:
        paths = []
        for nm, data in src:
            p = os.path.join(wd, _safe(nm))
            with open(p, "wb") as f:
                f.write(data)
            paths.append(p)
        tpl_path = None
        if tpl:
            tpl_path = os.path.join(wd, "tpl_" + _safe(tpl[0][0]))
            with open(tpl_path, "wb") as f:
                f.write(tpl[0][1])
        out_path = os.path.join(wd, "波兰考勤合并汇总.xlsx")

        _exec_merge_all(paths, out_path, tpl_path, None)

        if not os.path.isfile(out_path):
            return _fail("合并未生成输出文件，请检查考勤表格式是否为各站点标准考勤表。")
        data = _read(out_path)

        # 读回各表行数，便于用户核对（不改变任何输出内容）
        sheet_info = ""
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True)
            parts = []
            for s in wb.sheetnames:
                ws = wb[s]
                parts.append("%s %d 行" % (s, max(ws.max_row - 1, 0)))
            sheet_info = "　".join(parts)
            wb.close()
        except Exception:
            pass

        notes = ["考勤表 %d 份" % len(src)]
        if tpl:
            notes.append("表头模板: %s" % _basename(tpl[0][0]))
        else:
            notes.append("未提供表头模板（文件名含「汇总字段」或「模板」即自动识别），"
                         "本次不生成『Report汇总(指定表头)』表")
        if sheet_info:
            notes.append(sheet_info)
        if _dialog_text():
            notes.append(_dialog_text())
        info = "· ".join(notes)
        return _emit([("波兰考勤合并汇总.xlsx", data)], info, "波兰考勤合并汇总")
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def _exec_merge_all(att_paths, out_path, tpl_path, raw_out):
    """执行 06 的 merge_all.py。

    该脚本在【模块级】就跑完整套合并（第 48 行 `FILES,OUT,... = parse_args()` 之后
    一路执行到末尾保存），所以不能 import 一次就算了 —— 必须每次带着新的 sys.argv
    重新 exec 一遍。parse_args 用的是 parse_known_args，不会因为多余参数报错。
    """
    _install_gui_stubs()
    tdir = os.path.dirname(resolve("06_attendance/report_summary.py"))
    argv = ["merge_all.py", "--files"] + list(att_paths) + ["--out", out_path]
    if tpl_path and os.path.isfile(tpl_path):
        argv += ["--template", tpl_path]
    else:
        argv += ["--no-report"]
    if raw_out:
        argv += ["--raw-out", raw_out]

    import importlib.util
    old_argv = sys.argv[:]
    added = False
    if tdir not in sys.path:
        sys.path.insert(0, tdir)      # merge_all.py 末尾 import report_summary
        added = True
    try:
        sys.argv = argv
        spec = importlib.util.spec_from_file_location(
            "pl_merge_run_%d" % (len(_LOADED) + int(_ts()) % 100000),
            os.path.join(tdir, "merge_all.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)      # 整个合并在此执行完毕
    finally:
        sys.argv = old_argv
        if added:
            try:
                sys.path.remove(tdir)
            except ValueError:
                pass


def _ts():
    import time
    return time.time()


# ------------------------------------------------------------- 07 P45 ---

def core_p45(files, opt=None):
    m = _load("07_p45", "07_p45/p45_tool.py")
    pdfs = _pick(files, {".pdf"})
    if not pdfs:
        return _fail("未收到 PDF 文件。本工具需英国 P45 表格 PDF（含 NI Number / Leaving date）。")

    wd = tempfile.mkdtemp(prefix="pl_p45_")
    try:
        produced, failed, details = [], [], []
        for nm, data in pdfs:
            base = _basename(nm)
            sub = os.path.join(wd, "d%d" % len(produced + failed))
            os.makedirs(sub)
            p = os.path.join(sub, _safe(base))
            with open(p, "wb") as f:
                f.write(data)
            before = set(os.listdir(sub))
            try:
                ok, msg = m.process_pdf(p, keep_original=True, log=lambda *a, **k: None)
            except Exception as e:
                ok, msg = False, "处理异常: %s" % e
            new = [x for x in os.listdir(sub) if x not in before]
            if ok and new:
                target = new[0]
                produced.append((target, _read(os.path.join(sub, target))))
                details.append("%s → %s" % (base, target))
            else:
                dn = _doc_note(data, "英国 P45 处理（重命名+加密）")
                failed.append("%s（%s%s）" % (
                    base, _humanize_p45_error(msg), ("；" + dn) if dn else ""))
        notes = []
        if details:
            notes.append("；".join(details[:20]))
        if failed:
            notes.append("失败: " + "；".join(failed))
        info = "%d 名员工（P45 重命名并加密）/ 共 %d 个 PDF%s" % (
            len(produced), len(pdfs), "　" + "　".join(notes) if notes else "")
        if not produced:
            return _fail("未生成任何 P45 文件。" + ("　".join(notes) if notes else ""))
        return _emit(produced, info, "P45输出")
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ------------------------------------------------ 08 英国养老金信函重命名 ---

def core_pension(files, opt=None):
    m = _load("08_pension", "08_pension_rename/pdf_renamer.py")
    pdfs = _pick(files, {".pdf"})
    if not pdfs:
        return _fail("未收到 PDF 文件。本工具需 AE Eligible/Non-Eligible Job Holder Letter PDF。")

    produced, ok, miss, used = [], 0, [], set()
    for nm, data in pdfs:
        base = _basename(nm)
        wd = tempfile.mkdtemp(prefix="pl_pen_")
        try:
            p = os.path.join(wd, _safe(base))
            with open(p, "wb") as f:
                f.write(data)
            name, why = None, ""
            try:
                name = m.extract_name(p)
            except Exception as e:
                why = "提取异常: %s" % e
            if name:
                good, why2 = _plausible_person_name(name)
                if not good:
                    name, why = None, "姓名不可信（%s）：%s" % (why2, name)
            if name:
                new = m.build_new_filename(base, name)
                produced.append((_unique_name(_safe(new), used), data))
                ok += 1
            else:
                # 不做「猜名字」式改名：宁可显式标注未识别，也不产出错误姓名
                dn = _doc_note(data, "英国养老金信函重命名")
                miss.append("%s（未识别到收件人姓名：%s%s）" % (
                    base, why or "信函中没有 Dear 行/姓名行", ("；" + dn) if dn else ""))
                produced.append((_unique_name(_safe("【未识别姓名】" + base), used), data))
        finally:
            shutil.rmtree(wd, ignore_errors=True)

    notes = []
    if miss:
        notes.append("未识别 %d 个: %s" % (len(miss), "；".join(miss[:20])))
    info = "重命名 %d 个 / 共 %d 个 PDF%s" % (
        ok, len(pdfs), "　" + "　".join(notes) if notes else "")
    if ok == 0:
        return _fail("未识别到任何收件人姓名（已保留原名，避免错误重命名）。"
                     + ("　".join(notes) if notes else ""))
    return _emit(produced, info, "养老金信函重命名")


# ------------------------------------------------- 09 爱尔兰工资单处理 ---

def core_irish(files, opt=None):
    m = _load("09_irish", "09_irish/irish_payslip_tool.py")
    pdfs = _pick(files, {".pdf"})
    if not pdfs:
        return _fail("未收到 PDF 文件。本工具需爱尔兰工资单 PDF（含 PPS Number）。")

    wd = tempfile.mkdtemp(prefix="pl_ie_")
    try:
        produced, ok, miss, used = [], 0, [], set()
        for nm, data in pdfs:
            base = _basename(nm)
            src = os.path.join(wd, _safe(base))
            with open(src, "wb") as f:
                f.write(data)
            try:
                res = m.parse_pdf(src)
            except Exception as e:
                produced.append((_unique_name(_safe("【未识别-未加密】" + base), used), data))
                miss.append("%s（解析异常: %s）" % (base, e))
                continue
            name = getattr(res, "name", None)
            pps = getattr(res, "pps", None)
            err = getattr(res, "error", None)
            if not name or not pps:
                # 不能把「原封不动」的文件当成成功产物：文件名显式标注未识别/未加密
                dn = _doc_note(data, "爱尔兰工资单处理")
                produced.append((_unique_name(_safe("【未识别-未加密】" + base), used), data))
                miss.append("%s（%s%s）" % (base, err or "未识别到姓名或 PPS", ("；" + dn) if dn else ""))
                continue
            new = m.build_new_filename(base, name)
            enc = os.path.join(wd, "enc_" + _safe(new))
            try:
                m.encrypt_pdf_to_temp(src, enc, pps)   # 原逻辑：AES-256，密码=PPS
                payload = _read(enc)
            except Exception as e:
                payload = data
                miss.append("%s（加密失败已输出未加密件: %s）" % (base, e))
            produced.append((_unique_name(_safe(new), used), payload))
            ok += 1

        notes = []
        if miss:
            notes.append("异常 %d 个: %s" % (len(miss), "；".join(miss[:20])))
        info = "%d 名员工（重命名+AES加密）/ 共 %d 个 PDF%s" % (
            ok, len(pdfs), "　" + "　".join(notes) if notes else "")
        if ok == 0:
            return _fail("未识别到任何爱尔兰工资单（未做重命名与加密）。"
                         + ("　".join(notes) if notes else ""))
        return _emit(produced, info, "爱尔兰工资单处理")
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ------------------------------------------------- 10 德国工资单提取 ---

def _de_diag_note(diag, verbose=False):
    """德国（Lohnjournal）解析诊断 → 一句人话。

    失败时必须带上（回答了「为什么一行都没解析出来」）；
    成功时只带真正像告警的（旋转 / 单页异常 / 填充率偏低），避免噪音。
    """
    if not isinstance(diag, dict) or not diag:
        return ""
    bits = []
    if verbose and diag.get("anchors_source"):
        bits.append("锚点来源：%s" % diag["anchors_source"])
    if verbose and diag.get("page_size"):
        bits.append("页面尺寸：%s" % diag["page_size"])
    fr = diag.get("fill_rate")
    if fr is not None and fr < 1.0:
        bits.append("金额填充率 %.0f%%" % (fr * 100))
    bits.extend(str(n) for n in (diag.get("notes") or []))
    bits.extend(str(n) for n in (diag.get("page_errors") or []))
    return "；".join(bits)


def core_german(files, opt=None):
    m = _load("10_german", "10_german/lohnjournal_extractor.py")
    pdfs = _pick(files, {".pdf"})
    if not pdfs:
        if files:
            got = "、".join(sorted({(_ext(nm) or "无扩展名") for nm, _ in files}))
            return _fail("未收到 PDF 文件（本次上传的是：%s）。本工具需德国 Lohnjournal 报表 PDF；"
                         "若手上是已导出的 Excel，本工具不适用。" % got)
        return _fail("未收到任何文件。请上传德国 Lohnjournal 工资单 PDF。")

    wd = tempfile.mkdtemp(prefix="pl_de_")
    try:
        produced, failed, total, details = [], [], 0, []
        for nm, data in pdfs:
            base = _basename(nm)
            p = os.path.join(wd, _safe(base))
            with open(p, "wb") as f:
                f.write(data)
            diag = {}
            try:
                emps = m.extract_from_pdf(p, diag)
            except Exception as e:
                emps, err = [], "解析异常: %s" % e
            else:
                err = ""
            if not emps:
                dn = _doc_note(data, "德国工资单提取（Lohnjournal）")
                # 诊断不重复、不添噪音：解析器抛错时错误信息里已带「锚点来源」，
                # 无文本层（扫描件/坏文件/加密）时列位诊断对用户毫无意义。
                dbrief = (_de_diag_note(diag) if ("锚点来源" in err
                                                  or not _pdf_text_head(data).strip())
                          else _de_diag_note(diag, verbose=True))
                failed.append("%s（未解析到员工行%s%s%s）" % (
                    base, ("；" + err) if err else "", ("；" + dn) if dn else "",
                    ("；" + dbrief) if dbrief else ""))
                continue
            outp = os.path.join(wd, os.path.splitext(_safe(base))[0] + ".xlsx")
            m.write_excel(emps, outp)
            if os.path.isfile(outp):
                produced.append((os.path.splitext(base)[0] + ".xlsx", _read(outp)))
                total += len(emps)
                dbrief = _de_diag_note(diag)
                details.append("%s: %d 人%s" % (
                    base, len(emps), ("（%s）" % dbrief) if dbrief else ""))
            else:
                failed.append("%s（Excel 未生成）" % base)

        notes = []
        if details:
            notes.append("；".join(details))
        if failed:
            notes.append("失败: " + "；".join(failed))
        info = "%d 名员工（%d 个 PDF）%s" % (
            total, len(pdfs), "　" + "　".join(notes) if notes else "")
        if not produced:
            return _fail("未提取到任何员工数据。" + ("　".join(notes) if notes else ""))
        return _emit(produced, info, "德国工资单提取")
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ===========================================================================
# 六、注册到工作台
# ===========================================================================

PL_META = [
    # id, 名称, 描述, country, category, accept, core, zipstem
    dict(id="pl_pesel", name="波兰 PESEL 信息提取", country="波兰", category="海外核算",
         accept=".pdf", core=core_pesel, source="波兰工具箱",
         drop_hint="拖入波兰工资单/合同/表单 PDF（可多份，.pdf）",
         desc="上传波兰工资单/合同/表单 PDF（可多个），按 PESEL 标签、Nr/Numer 标签、11 位数字、"
              "OCR 易混字符(0/O、1/I/l、5/S、8/B 等)四重策略定位员工 PESEL，"
              "并用加权校验位复核，输出 Excel（序号/文件名/PESEL/是否找到/校验位/说明）。"),
    dict(id="pl_payroll", name="波兰工资单提取", country="波兰", category="海外核算",
         accept=".pdf", core=core_payroll, source="波兰工具箱",
         drop_hint="拖入波兰工资单 PDF（可多份，.pdf，每份输出一个 Excel）",
         desc="上传波兰工资单 PDF（可多个），按坐标提取每位员工的基本工资、标准工时、总工时、"
              "Urlopy、ZUS、NN、Inne、Nadg.50、Nadg.100、Nocne，每份 PDF 输出一个 Excel。"),
    dict(id="pl_attendance", name="波兰考勤合并汇总", country="波兰", category="工资核算",
         accept=".xlsx", core=core_attendance, source="波兰工具箱",
         drop_hint="一次拖入各站点考勤表 xlsx（可多份；如需 Report汇总表，再拖入文件名含「汇总字段/模板」的 xlsx）",
         desc="一次拖入各站点考勤表 xlsx（可多份），合并生成『请假明细 / 月汇总 / 异常清单』，"
              "并把『异常清单』移到首张便于核对。如需『Report汇总(指定表头)』表，"
              "再拖入文件名含「汇总字段」或「模板」的 xlsx（不会并入无关站点数据）。"),
    dict(id="de_lohnjournal", name="德国工资单提取（Lohnjournal）", country="德国", category="海外核算",
         accept=".pdf", core=core_german,
         drop_hint="拖入德国 Lohnjournal 工资单 PDF（可多份，.pdf，每份输出一个 Excel；无需 import 模板，本工具不吃 xlsx）",
         desc="上传德国 Lohnjournal 工资单 PDF（可多个），按绘制锚点定位 32 列（Pers.-Nr. / St.Kl. / "
              "Name / Lohnsteuer / Gesamtbrutto / Auszahlungsbetrag 等）逐人提取，每份输出一个 Excel。"),
    dict(id="ie_payslip", name="爱尔兰工资单处理", country="爱尔兰", category="海外核算",
         accept=".pdf", core=core_irish,
         drop_hint="拖入爱尔兰工资单 PDF（可多份，.pdf，输出按姓名命名的加密 PDF）",
         desc="上传爱尔兰工资单 PDF（可多个），提取员工姓名与 PPS Number，输出"
              "『【姓名】原文件名.pdf』，并用 PPS 作为密码做 AES-256 加密（密码即 PPS）。"),
    dict(id="p45_process", name="英国 P45 处理（重命名+加密）", country="英国", category="海外核算",
         accept=".pdf", core=core_p45,
         drop_hint="拖入英国 P45 表格 PDF（可多份，.pdf，输出重命名并按 NI Number 加密的 PDF）",
         desc="上传英国 P45 表格 PDF（可多个），提取姓氏/名/离职日期/NI Number，"
              "输出『姓 名 - 离职日期 - P45.pdf』并用 NI Number 作为密码做 AES-256 加密。"),
    dict(id="pension_rename", name="英国养老金信函重命名", country="英国", category="海外核算",
         accept=".pdf", core=core_pension,
         drop_hint="拖入 AE Eligible / Non-Eligible Job Holder Letter PDF（可多份，.pdf）",
         desc="上传 AE Eligible / Non-Eligible Job Holder Letter PDF（可多个），"
              "按 Dear 锚点（回退按版面坐标）提取收件人姓名，输出『【姓名】原文件名.pdf』。"),
    dict(id="pl_pdf_encrypt", name="PDF/Excel 批量加密", country="通用", category="工具",
         accept=".pdf/.xlsx/.xls", core=core_encrypt,
         drop_hint="一次拖入：密码表 xlsx（含「文件名」+「PESEL/密码」列）+ 要加密的 PDF/xlsx/xls（可多份）",
         desc="一次拖入「文件名 → PESEL/密码」Excel 密码表 + 要加密的 PDF/xlsx/xls（可多个），"
              "自动识别表头列并按文件名匹配密码，逐个用 128 位口令加密输出；"
              "xls 会先转为 xlsx 再加密（密码表本身不再重复加密）。"),
    dict(id="pl_pdf_rename", name="PDF 批量重命名（按工号）", country="通用", category="工具",
         accept=".pdf/.xlsx", core=core_rename,
         drop_hint="一次拖入：映射表 xlsx（含「文件名称」+「工号」列）+ 要改名的 PDF（可多份）",
         desc="一次拖入「文件名称 → 工号」映射表 xlsx + 要改名的 PDF（可多个），"
              "自动识别列名并匹配（精确匹配优先，未中再按包含匹配重试），输出以工号命名的 PDF。"),
    dict(id="pl_pdf_sanitize", name="PDF 隐私脱敏（PESEL 打码）", country="波兰", category="工具",
         accept=".pdf", core=core_sanitize, source="波兰工具箱",
         drop_hint="拖入含 PESEL 等敏感信息的 PDF（可多份，.pdf；可另加自定义关键词 .txt）",
         desc="上传含 Pracownik/Data wystawienia/PESEL 等敏感信息的 PDF（可多个），"
              "整行涂白或按前导关键词+位数精确涂白目标数字，再按 200dpi 输出 PNG 并自动裁白边。"
              "可另拖入一个 .txt 自定义关键词（每行一个，支持『关键词+位数』写法）。"),
]

PL_HINTS = {
    "pl_pesel": "波兰 PESEL 提取：需含 PESEL 号（11 位加权校验）的文本型 PDF。"
                "自查：① 是否扫描件（无可提取文本）？② 号码是否被拆行/加水印遮挡？③ 是否非波兰证件？",
    "pl_payroll": "波兰工资单提取：需文本型 PDF —— 多人明细表（含 LP 序号列 + Pracownik 列），"
                  "或单人 Kwitek wypłaty（按 Pracownik:/Stawka:/Czas pracy/Urlopy/Nadgodziny 标签兜底解析）。"
                  "自查：① 是否扫描件？② 是否与既有站点模板排版差异过大？③ 是否波兰语工资单？",
    "pl_attendance": "波兰考勤合并：需为各站点标准考勤表 xlsx（含人员 Sheet + 排班/Norma 表）。"
                     "自查：① 是否上传了非考勤表？② Sheet 结构是否被改名/裁剪？"
                     "③ 需要 Report汇总(指定表头) 表时是否忘了拖入『波兰汇总字段.xlsx』类模板？",
    "de_lohnjournal": "德国 Lohnjournal 提取：需为含 Pers.-Nr./St.Kl./Name 等 32 列且带绘制锚线的文本型 PDF。"
                      "自查：① 是否扫描件？② 是否 Lohnjournal 报表（而非单张工资单）？"
                      "③ 页面是否被缩放/裁剪/旋转过（打印缩放、另存、截图转 PDF 会丢失表格锚线）？",
    "ie_payslip": "爱尔兰工资单：需含员工姓名行与 PPS Number 标签的文本型 PDF。"
                  "自查：① 是否扫描件？② 是否该雇主(YUNEXPRESS IRELAND)的标准工资单？",
    "p45_process": "英国 P45：需含 NI Number（如 AB123456C）与 Leaving date 的 HMRC P45 表格 PDF。"
                   "自查：① 是否 P45 而非 P60/Payslip？② 是否扫描件？",
    "pension_rename": "养老金信函重命名：需为 AE Eligible / Non-Eligible Job Holder Letter PDF，"
                      "需能在首页定位收件人姓名行或 Dear 行。识别的姓名会做真实性校验"
                      "（含数字/机构词如 Oddział NFZ 的一律判为不可信，保留原名并标注【未识别姓名】）。"
                      "自查：① 是否该机构信函？② 是否扫描件？",
    "pl_pdf_encrypt": "批量加密：需同时提供密码表 xlsx（含「文件名」列与「PESEL/密码」列）+ 待加密文件。"
                      "自查：① 是否只拖了文件没拖密码表？② 文件名与密码表首列是否对得上？"
                      "③ 文件是否已经是加密状态（已加密会被跳过）？",
    "pl_pdf_rename": "按工号重命名：需同时提供映射表 xlsx（含「文件名称」列与「工号」列）+ 待改名 PDF。"
                     "自查：① 是否只拖了 PDF 没拖映射表？② 映射表首列是否为文件名？"
                     "③ 是否匹配到多个同名（包含匹配歧义）？",
    "pl_pdf_sanitize": "隐私脱敏：需为含关键词文本的 PDF（默认 Pracownik:/Data wystawienia:/pracownika/PESEL:+11）。"
                       "自查：① 是否扫描件（涂白依赖文本层）？② 关键词与文档是否一致（可用 .txt 自定义）？",
}


def bind(tool_id, core):
    """返回 (单文件处理函数, 多文件处理函数)，两者共用同一实现。"""
    def _single(filename, raw):
        return core([(_basename(filename), raw)], None)

    def _multi(payload):
        fl = []
        for f in (payload.get("files") or []):
            nm = f.get("filename") or "input.bin"
            d = f.get("data") or ""
            try:
                fl.append((_basename(nm), base64.b64decode(d)))
            except Exception:
                fl.append((_basename(nm), b""))
        if not fl:
            return _fail("未收到文件。")
        return core(fl, None)

    return _single, _multi


def register_all(register_tool):
    """由 web_extractor.py 在模块加载时调用一次，注册全部 10 个工具卡片。"""
    n = 0
    for meta in PL_META:
        single, multi = bind(meta["id"], meta["core"])
        register_tool(
            meta["id"], meta["name"], meta["desc"],
            single, accept=meta["accept"], enabled=True,
            process_multi=multi,
            en_name=meta["id"].upper(),
            version="v1.0",
            status_text="已上线",
            last_batch="-",
            last_result="-",
            category=meta["category"],
            country=meta["country"],
            # 来源标签只跟「国家=波兰」的工具走：把波兰工具箱的名字挂到德国/爱尔兰/英国
            # 工具上，用户会以为工具搞混了（2026-09-14 第五轮，见 避坑清单 §14）
            source=meta.get("source", ""),
            # 各工具拖拽区提示语必须各写各的：multi 工具早期一律显示
            # 法语 import 工具那句「源表 + 空白 import 模板」，德国等无模板的工具会误导用户
            drop_hint=meta.get("drop_hint", ""),
        )
        n += 1
    print("[OK] 波兰工资考勤工具箱已整合: %d 个工具" % n)
    return n


def selfcheck():
    """自检：桩是否就绪 + 各工具源文件是否可定位。"""
    _install_gui_stubs()
    lines = ["poland_tools 根目录: " + tools_root(), ""]
    lines += loaded_report()
    return lines


if __name__ == "__main__":
    for ln in selfcheck():
        print(ln)
