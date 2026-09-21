"""
PDF Pension Letter Renamer
==========================

用途:从英国养老金 AE Eligible Job Holder Letter PDF 的第1页指定位置(红框处)
     提取收件人姓名,并用 "【姓名】原文件名" 格式批量重命名。

使用方法:
    1. 双击运行本文件(Windows)或在命令行执行:
         python pdf_renamer.py
    2. 点击"选择 PDF 文件夹",选择包含待重命名 PDF 的目录
    3. 在表格中核对/编辑识别出的姓名
    4. 点击"执行重命名"完成批量改名
    5. 如需回滚,点击"撤销上一次重命名"

姓名提取位置:PDF 第1页 y ∈ [210, 245] 区间(物理坐标,页面顶端为0)
"""

import os
import re
import sys
import shutil
import unicodedata
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import Optional

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:
    try:
        import fitz  # PyMuPDF < 1.24
    except ImportError:
        raise SystemExit(
            "缺少依赖 pymupdf,请先执行:\n"
            "  pip install pymupdf"
        )


# ---------------------------------------------------------------------------
# 姓名提取核心逻辑
# ---------------------------------------------------------------------------

# 策略:
#   1. 主策略:"Dear {Name}" 锚点 — 跨 1 页 / 2 页版式都稳
#   2. 回退: 在 PDF 第 1 页物理坐标姓名行约束区间内查找
#
# 版式参考(以 The Pensions Regulator 自动入职信模板为准):
#   - 2 页版(Eligible):    姓名行 y0 ≈ 220, "Dear" 行 y0 ≈ 344
#   - 1 页版(Non-Eligible): 姓名行 y0 ≈ 155, "Dear" 行 y0 ≈ 276
#   因为版式不同造成整体偏移,所以用"Dear"锚点最稳。

DEAR_PATTERN = re.compile(r"^Dear\s+(.+?)\s*[,.;:]?\s*$", re.IGNORECASE)

# 回退方案:姓名行物理坐标约束(顶端为 0,单位:pt)
NAME_Y0_MIN = 100.0
NAME_Y0_MAX = 300.0
NAME_X0_MIN = 50.0
NAME_X0_MAX = 350.0

# 安全清洗:Windows 文件名禁止的字符 <>:"/\|?* 以及控制字符
_INVALID_FN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _extract_by_dear_anchor(page) -> Optional[str]:
    """在页面中找 'Dear {Name}' 这一行,从后面抓取姓名。"""
    for b in page.get_text("dict").get("blocks", []):
        for line in b.get("lines", []):
            txt = "".join(span["text"] for span in line.get("spans", [])).strip()
            m = DEAR_PATTERN.match(txt)
            if m:
                candidate = m.group(1).strip(" .,;:")
                candidate = re.sub(r"\s+", " ", candidate)
                if candidate:
                    return candidate
    return None


def _extract_by_position(page) -> Optional[str]:
    """回退方案:在姓名行物理坐标区间内查找最靠上的有效文本。"""
    spans_in_band = []
    for b in page.get_text("dict").get("blocks", []):
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                x0, y0, x1, y1 = span["bbox"]
                if not (NAME_Y0_MIN <= y0 <= NAME_Y0_MAX):
                    continue
                if not (NAME_X0_MIN <= x0 <= NAME_X0_MAX):
                    continue
                txt = span["text"]
                if txt and txt.strip():
                    spans_in_band.append((y0, x0, txt))

    if not spans_in_band:
        return None

    # 同行(y 接近)按 x 排序拼接
    spans_in_band.sort(key=lambda t: (t[0], t[1]))
    rows = []
    cur_y, cur_text = None, []
    for y, x, t in spans_in_band:
        if cur_y is None or abs(y - cur_y) <= 3.0:
            cur_text.append(t)
            cur_y = y if cur_y is None else cur_y
        else:
            rows.append(" ".join(cur_text))
            cur_text = [t]
            cur_y = y
    if cur_text:
        rows.append(" ".join(cur_text))

    if not rows:
        return None

    # 取最靠上(最早)的一行作为姓名
    name = re.sub(r"\s+", " ", rows[0]).strip().strip(" .,;:")
    return name if name else None


def extract_name(pdf_path: str) -> Optional[str]:
    """从 PDF 第 1 页提取姓名(主:Dear 锚点,回退:坐标定位)。"""
    try:
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return None
        page = doc[0]

        name = _extract_by_dear_anchor(page)
        if not name:
            name = _extract_by_position(page)

        doc.close()
        return name
    except Exception as exc:  # noqa: BLE001
        print(f"[extract_name error] {pdf_path}: {exc}", file=sys.stderr)
        return None


def sanitize_filename(name: str) -> str:
    """把姓名清洗为可作为文件名的字符串。"""
    name = unicodedata.normalize("NFC", name)
    name = _INVALID_FN_CHARS.sub("_", name)
    name = name.rstrip(". ").strip()
    return name


def build_new_filename(original_name: str, extracted_name: str) -> str:
    """拼接为 【姓名】原文件名.pdf"""
    safe_name = sanitize_filename(extracted_name)
    if not safe_name:
        safe_name = "Unknown"
    stem, ext = os.path.splitext(original_name)
    if not ext:
        ext = ".pdf"
    return f"【{safe_name}】{stem}{ext}"


# ---------------------------------------------------------------------------
# 重命名操作(支持撤销)
# ---------------------------------------------------------------------------

class RenameSession:
    """记录一次批量重命名前后映射,用于撤销。"""

    def __init__(self, folder: str):
        self.folder = folder
        self.records: list[tuple[str, str]] = []  # [(old_path, new_path), ...]

    def apply(self, mapping: list[tuple[str, str]]) -> None:
        """mapping: [(old_path, new_path), ...]"""
        for old, new in mapping:
            if not os.path.isfile(old):
                continue
            # 同名直接覆盖(os.replace 原子);跨设备则拷贝+删除
            try:
                os.replace(old, new)
            except OSError:
                shutil.copy2(old, new)
                os.remove(old)
            self.records.append((old, new))

    def undo(self) -> int:
        """撤销本会话的全部改名,返回成功条数。"""
        ok = 0
        for old, new in reversed(self.records):
            if os.path.isfile(new) and not os.path.exists(old):
                try:
                    os.replace(new, old)
                    ok += 1
                except OSError:
                    try:
                        shutil.copy2(new, old)
                        os.remove(new)
                        ok += 1
                    except Exception as exc:  # noqa: BLE001
                        print(f"[undo error] {new} -> {old}: {exc}", file=sys.stderr)
        self.records.clear()
        return ok


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Pension Letter Renamer")
        self.geometry("1100x600")
        self.minsize(900, 480)

        self.selection_var = tk.StringVar(value="未选择任何 PDF")
        self.status_var = tk.StringVar(value="请添加要处理的 PDF 文件")
        self.rows: list[dict] = []  # 每项 {path, name, new_name, original_name}
        self._selected_paths: set[str] = set()  # 用户已显式选择的文件(去重)
        self._last_session: Optional[RenameSession] = None

        self._build_ui()
        self._set_status("就绪")

    # ---------------- UI ----------------
    def _build_ui(self):
        # 顶部:文件选择(只处理用户显式选中的 PDF,绝不擅自扫描目录)
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        ttk.Button(top, text="➕ 添加 PDF 文件", command=self.on_pick_files).pack(side=tk.LEFT)
        ttk.Button(top, text="✖ 清空列表", command=self.on_clear).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Entry(top, textvariable=self.selection_var, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=8
        )
        ttk.Button(top, text="重新提取", command=self.on_refresh).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            top, text="打开所在位置", command=self.on_open_location
        ).pack(side=tk.LEFT, padx=2)

        # 中间:表格
        mid = ttk.Frame(self, padding=(8, 0))
        mid.pack(fill=tk.BOTH, expand=True)
        cols = ("original", "name", "new")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("original", text="原文件名")
        self.tree.heading("name", text="识别姓名(可双击编辑)")
        self.tree.heading("new", text="新文件名(预览)")
        self.tree.column("original", width=380, anchor=tk.W)
        self.tree.column("name", width=260, anchor=tk.W)
        self.tree.column("new", width=400, anchor=tk.W)

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(mid, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)

        # 双击编辑姓名
        self.tree.bind("<Double-1>", self.on_edit_cell)
        # 回车保存编辑
        self.tree.bind("<Return>", self.on_edit_cell)
        self._edit_entry: Optional[tk.Entry] = None

        # 底部:操作
        bot = ttk.Frame(self, padding=8)
        bot.pack(fill=tk.X)
        ttk.Button(
            bot, text="▶ 执行重命名", command=self.on_apply
        ).pack(side=tk.LEFT)
        ttk.Button(
            bot, text="↶ 撤销上一次重命名", command=self.on_undo
        ).pack(side=tk.LEFT, padx=6)
        ttk.Separator(bot, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(bot, text="退出", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Label(bot, textvariable=self.status_var, foreground="#666").pack(
            side=tk.LEFT, padx=12
        )

    # ---------------- 事件 ----------------
    def on_pick_files(self):
        """用户显式选择一个或多个 PDF。只处理这些被选中的文件,绝不扫描目录。"""
        paths = filedialog.askopenfilenames(
            title="选择要处理的 PDF 文件(可多选)",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if not paths:
            return
        added = 0
        for p in paths:
            p = os.path.normpath(p)
            if p in self._selected_paths:
                continue
            if not os.path.isfile(p):
                continue
            self._selected_paths.add(p)
            added += 1
        if added == 0:
            messagebox.showinfo("提示", "所选文件已在列表中")
            return
        self._refresh_from_selection()

    def on_clear(self):
        """清空已选文件列表和表格。"""
        self._selected_paths.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.rows.clear()
        self.selection_var.set("未选择任何 PDF")
        self._set_status("已清空列表")

    def on_open_location(self):
        """打开第一个选中文件所在的目录(用户主动触发)。"""
        if not self._selected_paths:
            messagebox.showwarning("提示", "请先添加 PDF 文件")
            return
        folder = os.path.dirname(next(iter(self._selected_paths)))
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # noqa: S606
            elif sys.platform == "darwin":
                os.system(f'open "{folder}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("错误", str(exc))

    def on_refresh(self):
        """基于当前已选文件重新提取姓名(不扫描目录)。"""
        if not self._selected_paths:
            messagebox.showwarning("提示", "请先添加 PDF 文件")
            return
        self._refresh_from_selection()

    def _refresh_from_selection(self):
        """根据 self._selected_paths 重新填充表格并提取姓名。"""
        self._set_status("正在提取姓名…")
        self.update_idletasks()

        # 清空表
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self.rows.clear()

        ok, fail = 0, 0
        for path in sorted(self._selected_paths):
            fname = os.path.basename(path)
            name = extract_name(path) or ""
            new_name = build_new_filename(fname, name) if name else f"[无法识别] {fname}"
            self.rows.append(
                {
                    "path": path,
                    "original_name": fname,
                    "name": name,
                    "new_name": new_name,
                }
            )
            self.tree.insert(
                "", tk.END,
                values=(fname, name, new_name),
                tags=("ok" if name else "fail",),
            )
            if name:
                ok += 1
            else:
                fail += 1

        self.tree.tag_configure("ok", foreground="#1a1a1a")
        self.tree.tag_configure("fail", foreground="#c0392b")
        n = len(self._selected_paths)
        self.selection_var.set(f"已选 {n} 个 PDF | 识别成功 {ok},失败 {fail}")
        self._set_status(f"共 {n} 个 PDF,识别成功 {ok},失败 {fail}")

    def on_edit_cell(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id or col_id != "#2":  # 只允许编辑"姓名"列
            return
        if self._edit_entry is not None:
            self._edit_entry.destroy()
            self._edit_entry = None

        x, y, w, h = self.tree.bbox(row_id, column=col_id)
        current = self.tree.set(row_id, "name")
        entry = tk.Entry(self.tree)
        entry.insert(0, current)
        entry.select_range(0, tk.END)
        entry.focus()
        entry.place(x=x, y=y, width=w, height=h)
        self._edit_entry = entry

        def commit(_evt=None):
            new_val = entry.get().strip()
            self.tree.set(row_id, "name", new_val)
            # 同步更新 rows
            idx = self.tree.index(row_id)
            if 0 <= idx < len(self.rows):
                self.rows[idx]["name"] = new_val
                if new_val:
                    self.rows[idx]["new_name"] = build_new_filename(
                        self.rows[idx]["original_name"], new_val
                    )
                else:
                    self.rows[idx]["new_name"] = (
                        f"[无法识别] {self.rows[idx]['original_name']}"
                    )
                self.tree.set(row_id, "new", self.rows[idx]["new_name"])
            entry.destroy()
            self._edit_entry = None

        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)
        entry.bind("<Escape>", lambda e: (entry.destroy(), setattr(self, "_edit_entry", None)))

    def on_apply(self):
        if not self.rows:
            messagebox.showinfo("提示", "没有可重命名的 PDF")
            return
        mapping: list[tuple[str, str]] = []
        missing = []
        for r in self.rows:
            if not r["name"]:
                missing.append(r["original_name"])
                continue
            new_path = os.path.join(os.path.dirname(r["path"]), r["new_name"])
            if os.path.isfile(new_path):
                # 已存在同名目标,跳过并提示
                missing.append(f"{r['original_name']} -> {r['new_name']} (目标已存在)")
                continue
            mapping.append((r["path"], new_path))

        if not mapping:
            messagebox.showwarning("提示", "没有可执行的重命名操作(全部失败或目标已存在)")
            return

        msg = f"将重命名 {len(mapping)} 个 PDF"
        if missing:
            msg += f"\n\n以下 {len(missing)} 个将被跳过:\n  - " + "\n  - ".join(missing[:10])
            if len(missing) > 10:
                msg += f"\n  ... 还有 {len(missing) - 10} 个"
        if not messagebox.askyesno("确认重命名", msg):
            return

        session = RenameSession("selected files")
        try:
            session.apply(mapping)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("错误", f"重命名失败:{exc}")
            return

        self._last_session = session
        # 更新已选文件列表为新路径,方便后续再次操作
        old_set = {old for old, _ in mapping}
        self._selected_paths = (self._selected_paths - old_set) | {new for _, new in mapping}
        self._set_status(f"✓ 完成 {len(mapping)} 个重命名(可撤销)")
        messagebox.showinfo(
            "完成",
            f"已重命名 {len(mapping)} 个 PDF。\n如需回滚请点击「撤销上一次重命名」。",
        )
        self.on_refresh()

    def on_undo(self):
        if not self._last_session or not self._last_session.records:
            messagebox.showinfo("提示", "没有可撤销的重命名记录")
            return
        if not messagebox.askyesno(
            "确认撤销",
            f"将撤销 {len(self._last_session.records)} 个重命名操作,是否继续?",
        ):
            return
        n = self._last_session.undo()
        self._set_status(f"↶ 已撤销 {n} 个重命名")
        self._last_session = None
        self.on_refresh()

    # ---------------- 辅助 ----------------
    def _set_status(self, text: str):
        self.status_var.set(text)


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
