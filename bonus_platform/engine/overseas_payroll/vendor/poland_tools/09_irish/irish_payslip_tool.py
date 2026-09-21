# -*- coding: utf-8 -*-
"""
Irish Payslip Tool — 爱尔兰工资单处理小工具
=================================================
用途: 批量处理 YUNEXPRESS IRELAND LIMITED 等公司的爱尔兰工资单 PDF,做两件事:
  1. 提取 PDF 第 1 行 "Month" 关键字之前的姓名,按 `【姓名】原文件名.pdf` 重命名
  2. 提取完整的 PPS number (7位数字 + 1~2字母,如 4040912G / 9529697HA),
     作为 PDF 打开密码
     (AES-256 加密,默认禁止打印/复制/修改)

文件访问约束: 本工具 *只* 读取/修改用户在 GUI 中显式选择导入的 PDF 文件。
              不会扫描任何目录,不会访问未导入的本地文件。
"""

from __future__ import annotations

import os
import re
import sys
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import pymupdf  # PyMuPDF
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


# ============================================================================
#  PDF 内容解析
# ============================================================================

# 爱尔兰 PPS number 有两种合法格式:
#   旧版: 7 位数字 + 1 字母  (如 4040912G,  8 字符)
#   新版: 7 位数字 + 2 字母  (如 9529697HA, 9 字符)
# 注意:  在数字与字母之间不匹配(word char 边界),所以用显式 lookaround
PPS_PATTERN = re.compile(r"(?<!\w)(\d{7}[A-Z]{1,2})(?!\w)")
# 工具栏里 "Month" 关键词的正则: 匹配 "Month <N>" (后面可能跟 "(Ending ...)")
MONTH_PATTERN = re.compile(r"\bMonth\b", re.IGNORECASE)


@dataclass
class ParseResult:
    """从 PDF 中解析出的两条关键信息"""
    name: Optional[str] = None
    pps: Optional[str] = None
    name_band: list[tuple] = field(default_factory=list)  # 调试用:姓名段 span 列表
    pps_band: list[tuple] = field(default_factory=list)  # 调试用:PPS 段 span 列表
    error: Optional[str] = None  # 解析过程的错误说明


def _is_employee_name_line(line_spans: list[dict], page_h: float) -> bool:
    """判断一行 span 列表是否就是顶部的姓名行。
    启发: 整行 y0 在页面上半部 (y0 < 0.30*page_h),且右侧包含 'Month' 字样。
    """
    if not line_spans:
        return False
    y0 = line_spans[0]["bbox"][1]
    if y0 > page_h * 0.30:
        return False
    line_text = "".join(s["text"] for s in line_spans)
    return bool(MONTH_PATTERN.search(line_text))


def parse_pdf(pdf_path: str) -> ParseResult:
    """从爱尔兰工资单 PDF 提取姓名和 PPS number。

    姓名: 第 1 页顶部"姓名 + Month N"行中, "Month" 关键字左侧的所有文本。
    PPS:  标签 "PPS number" 同行右侧、符合 \\d{7}[A-Z]{1,2} 的字符串 (完整 PPS)。
    """
    res = ParseResult()
    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:  # noqa: BLE001
        res.error = f"打开失败: {exc}"
        return res

    if len(doc) == 0:
        doc.close()
        res.error = "PDF 无页面"
        return res

    try:
        page = doc[0]
        page_h = page.rect.height
        blocks = page.get_text("dict").get("blocks", [])

        # --- 第 1 步: 收集所有 line,按 (y0, x0) 排序 ---
        lines: list[tuple[float, list[dict]]] = []
        for b in blocks:
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                y0 = spans[0]["bbox"][1]
                lines.append((y0, spans))
        lines.sort(key=lambda t: t[0])

        # --- 第 2 步: 找"姓名 + Month"那一行 (顶部、含 Month) ---
        name_line_spans: Optional[list[dict]] = None
        for y0, spans in lines:
            if y0 > page_h * 0.30:  # 超过页面上 30% 就放弃
                break
            line_text = "".join(s["text"] for s in spans)
            if MONTH_PATTERN.search(line_text):
                name_line_spans = spans
                res.name_band = [
                    (s["bbox"][0], s["bbox"][1], s["text"]) for s in spans
                ]
                break

        if name_line_spans is not None:
            # 在 name 行内,以 "Month" 为分界,取左侧所有 span 拼接
            # 思路: 找到第一个含 "Month" 字样的 span,其 x0 作为分界
            month_split_x: Optional[float] = None
            for s in name_line_spans:
                if MONTH_PATTERN.search(s["text"]):
                    month_split_x = s["bbox"][0]
                    break
            if month_split_x is not None:
                left_spans = [s for s in name_line_spans if s["bbox"][1] < page_h * 0.20
                              and s["bbox"][2] < month_split_x]
                # 排序 + 拼接 + 清洗
                left_spans.sort(key=lambda s: s["bbox"][0])
                raw = "".join(s["text"] for s in left_spans)
                cleaned = re.sub(r"\s+", " ", raw).strip().strip(" .,;:")
                if cleaned:
                    res.name = cleaned

        # --- 第 3 步: 找 PPS number 标签同行右侧的值 ---
        pps_label_span: Optional[dict] = None
        for y0, spans in lines:
            for s in spans:
                if s["text"].strip().lower() == "pps number":
                    pps_label_span = s
                    break
            if pps_label_span:
                break

        if pps_label_span is not None:
            label_y0 = pps_label_span["bbox"][1]
            label_x1 = pps_label_span["bbox"][2]
            # 找 y0 接近 (差 < 2pt) 且 x0 > label_x1 的所有 span
            same_line_right = [
                s for y0, spans in lines
                for s in spans
                if abs(s["bbox"][1] - label_y0) < 2.0
                and s["bbox"][0] > label_x1
            ]
            res.pps_band = [
                (s["bbox"][0], s["bbox"][1], s["text"]) for s in same_line_right
            ]
            same_line_right.sort(key=lambda s: s["bbox"][0])
            # 逐 span 检查: PPS 一般独立成段,无需拼接
            for s in same_line_right:
                m = PPS_PATTERN.search(s["text"])
                if m:
                    res.pps = m.group(1)
                    break
            if not res.pps:
                # 回退: 加空格 join 再试(防 span 边界跨字段)
                joined = " ".join(s["text"] for s in same_line_right)
                m = PPS_PATTERN.search(joined)
                if m:
                    res.pps = m.group(1)

    except Exception as exc:  # noqa: BLE001
        res.error = f"解析失败: {exc}"
    finally:
        doc.close()

    return res


# ============================================================================
#  文件名处理
# ============================================================================

_FILENAME_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_for_filename(s: str) -> str:
    """把字符串清洗成合法的 Windows 文件名片段。"""
    s = _FILENAME_FORBIDDEN.sub("_", s)
    return s.strip(" .")


def build_new_filename(original_name: str, person_name: str) -> str:
    """生成 `【姓名】原文件名.pdf` 形式的新文件名。"""
    stem, ext = os.path.splitext(original_name)
    safe_name = sanitize_for_filename(person_name)
    if not safe_name:
        safe_name = "Unknown"
    return f"【{safe_name}】{stem}{ext}"


# ============================================================================
#  PDF 加密 (AES-256)
# ============================================================================

def encrypt_pdf_to_temp(src_pdf: str, dst_pdf: str, user_pw: str) -> None:
    """把 src_pdf 加密后写到 dst_pdf。
       - AES-256 加密
       - user_pw = PPS number (打开密码)
       - 权限限制: 0 (禁止打印/复制/修改/注释)
       - 写入是原子的: 先写临时文件,再 rename
    """
    doc = pymupdf.open(src_pdf)
    try:
        # 用临时文件,保证失败时不污染原文件
        tmp_dir = os.path.dirname(dst_pdf) or "."
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=tmp_dir)
        os.close(fd)
        try:
            doc.save(
                tmp_path,
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                user_pw=user_pw,
                owner_pw="yuxiang-secure-2026",  # 固定所有者密码,便于后续维护
                permissions=0,  # 完全禁止打印/复制/修改
                garbage=4,
            )
            shutil.move(tmp_path, dst_pdf)
        except Exception:
            # 清理临时文件
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise
    finally:
        doc.close()


# ============================================================================
#  GUI
# ============================================================================

class App(tk.Tk):
    """爱尔兰工资单小工具主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.title("爱尔兰工资单 — 姓名提取 + PPS 加密")
        self.geometry("1080x640")
        self.minsize(900, 520)

        # 当前导入的 PDF 列表 [{path, name, pps, new_name, error}]
        self.rows: list[dict] = []
        # 撤销栈: 上一次操作 [(原路径, 新路径, 是否加密), ...]
        self._undo_stack: list[dict] = []

        self._build_ui()

    # -----------------------------------------------------------------
    #  UI 构建
    # -----------------------------------------------------------------
    def _build_ui(self) -> None:
        # 顶部工具条
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)
        ttk.Button(top, text="➕ 添加 PDF 文件", command=self.on_add).pack(side=tk.LEFT)
        ttk.Button(top, text="✖ 清空列表", command=self.on_clear).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="🔄 重新提取", command=self.on_refresh).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="📁 打开所在位置", command=self.on_open_location).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        ttk.Button(
            top, text="▶ 重命名 + 加密", command=self.on_apply
        ).pack(side=tk.LEFT)
        ttk.Button(
            top, text="↶ 撤销上一次操作", command=self.on_undo
        ).pack(side=tk.LEFT, padx=4)

        # 中部表格
        mid = ttk.Frame(self, padding=(8, 0))
        mid.pack(fill=tk.BOTH, expand=True)

        cols = ("original", "name", "pps", "new_name", "status")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=18)
        self.tree.heading("original", text="原文件")
        self.tree.heading("name", text="提取姓名")
        self.tree.heading("pps", text="PPS number")
        self.tree.heading("new_name", text="新文件名（重命名后）")
        self.tree.heading("status", text="状态")
        self.tree.column("original", width=260, anchor="w")
        self.tree.column("name", width=150, anchor="w")
        self.tree.column("pps", width=100, anchor="center")
        self.tree.column("new_name", width=360, anchor="w")
        self.tree.column("status", width=80, anchor="center")
        self.tree.tag_configure("ok", foreground="#1a1a1a")
        self.tree.tag_configure("fail", foreground="#c0392b")
        self.tree.tag_configure("encrypted", foreground="#0a7d3b")

        vsb = ttk.Scrollbar(mid, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 双击姓名列可编辑
        self.tree.bind("<Double-1>", self._on_double_click)

        # 状态条
        self.status_var = tk.StringVar(value="请点击「➕ 添加 PDF 文件」选择要处理的工资单")
        bar = ttk.Frame(self, padding=8)
        bar.pack(fill=tk.X)
        ttk.Label(bar, textvariable=self.status_var, anchor="w").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

    # -----------------------------------------------------------------
    #  事件
    # -----------------------------------------------------------------
    def on_add(self) -> None:
        """用户显式选择 PDF 文件 (多选)。不会扫描任何目录。"""
        paths = filedialog.askopenfilenames(
            title="选择要处理的 PDF (可多选)",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if not paths:
            return
        added = 0
        for p in paths:
            # 去重
            if any(r["path"] == p for r in self.rows):
                continue
            self.rows.append(
                {
                    "path": p,
                    "original_name": os.path.basename(p),
                    "name": None,
                    "pps": None,
                    "new_name": "",
                    "error": "",
                }
            )
            added += 1
        if added == 0:
            messagebox.showinfo("提示", "所选文件已在列表中,无新增。")
        else:
            self._set_status(f"已添加 {added} 个文件,正在解析…")
        self._refresh_tree()
        self._reparse_all()

    def on_clear(self) -> None:
        if not self.rows:
            return
        if messagebox.askyesno("确认", f"清空当前 {len(self.rows)} 个文件的列表?（不影响磁盘文件）"):
            self.rows.clear()
            self._refresh_tree()
            self._set_status("已清空列表")

    def on_refresh(self) -> None:
        if not self.rows:
            messagebox.showinfo("提示", "列表为空")
            return
        self._reparse_all()

    def on_open_location(self) -> None:
        """在资源管理器中打开 *当前选中行* 所在目录(只读操作)。"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择一行")
            return
        idx = int(sel[0])
        path = self.rows[idx]["path"]
        folder = os.path.dirname(path)
        try:
            if sys.platform.startswith("win"):
                # 用 /select 高亮定位文件
                os.system(f'explorer /select,"{path}"')
            elif sys.platform == "darwin":
                os.system(f'open -R "{path}"')
            else:
                os.system(f'xdg-open "{folder}"')
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("错误", str(exc))

    def on_apply(self) -> None:
        """重命名 + 加密。弹窗确认后执行。"""
        if not self.rows:
            messagebox.showinfo("提示", "列表为空")
            return

        # 收集可执行项
        runnable = []
        for r in self.rows:
            if r["name"] and r["pps"] and r["new_name"]:
                runnable.append(r)
            elif r["name"] and not r["pps"]:
                r["error"] = "PPS 缺失"
            elif not r["name"] and r["pps"]:
                r["error"] = "姓名缺失"

        if not runnable:
            messagebox.showwarning("提示", "没有可执行的文件(姓名和 PPS 都必须成功提取)。")
            self._refresh_tree()
            return

        preview_lines = "\n".join(
            f"  {os.path.basename(r['path'])}\n    → {r['new_name']}  (PPS: {r['pps']})"
            for r in runnable
        )
        if not messagebox.askyesno(
            "确认执行",
            f"将对以下 {len(runnable)} 个 PDF 执行 **重命名 + PPS 加密 (AES-256)**:\n\n"
            f"{preview_lines}\n\n"
            f"加密后打开 PDF 需要输入 PPS number。\n确定继续?",
        ):
            return

        # 执行: 每个文件先加密到临时路径,再 rename 到新文件名
        results = []
        undo = []
        for r in runnable:
            src = r["path"]
            dst_dir = os.path.dirname(src)
            new_path = os.path.join(dst_dir, r["new_name"])
            try:
                encrypt_pdf_to_temp(src, new_path, r["pps"])
                # 加密成功 → 删除原文件
                os.remove(src)
                results.append((r, "OK", new_path))
                undo.append({
                    "old_path": src,
                    "new_path": new_path,
                    "was_encrypted": True,
                })
            except Exception as exc:  # noqa: BLE001
                results.append((r, f"失败: {exc}", None))
                # 清理可能已生成的加密文件
                if os.path.exists(new_path):
                    try:
                        os.remove(new_path)
                    except OSError:
                        pass

        if undo:
            self._undo_stack.append({"ops": undo})

        # 简化:已成功加密并重命名的行,在 rows 里更新为"已加密"状态
        # (用新路径替换旧路径,新文件名作为 original_name,这样状态列会显示"已加密")
        ok_new_paths = {np: (r["name"], r["pps"]) for r, st, np in results if st == "OK"}
        new_rows = []
        for r in self.rows:
            if r["path"] in ok_new_paths:
                name, pps = ok_new_paths[r["path"]]
                new_rows.append({
                    "path": r["path"],
                    "original_name": r["new_name"],   # 现在文件名已是新名
                    "name": name,
                    "pps": pps,
                    "new_name": "",
                    "error": "",
                    "encrypted": True,
                })
            else:
                new_rows.append(r)
        self.rows = new_rows
        ok_count = len(ok_new_paths)

        self._refresh_tree()

        ok_count = len([1 for _, st, _ in results if st == "OK"])
        fail_count = len(runnable) - ok_count
        fail_details = "".join(
            f"\n  ✗ {os.path.basename(r['path'])}: {st}"
            for r, st, _ in results if st != "OK"
        )

        if fail_count == 0:
            self._set_status(f"✓ 全部成功: {ok_count}/{len(runnable)}  (可撤销)")
            messagebox.showinfo(
                "执行成功",
                f"✓ 成功处理 {ok_count}/{len(runnable)} 个文件。\n\n"
                f"加密密码 = PPS number\n"
                f"如需回滚请点击「↶ 撤销上一次操作」。",
            )
        else:
            self._set_status(
                f"⚠ 部分失败: 成功 {ok_count}, 失败 {fail_count}  (可撤销成功的)"
            )
            messagebox.showwarning(
                "部分失败",
                f"成功 {ok_count} 个,失败 {fail_count} 个:{fail_details}\n\n"
                f"成功的文件已加密,可点击「↶ 撤销上一次操作」回滚。\n"
                f"请检查失败文件后重试。",
            )

    def on_undo(self) -> None:
        if not self._undo_stack:
            messagebox.showinfo("提示", "没有可撤销的操作")
            return
        last = self._undo_stack.pop()
        restored = 0
        for op in last["ops"]:
            # 撤销: 把加密的"新文件"恢复成原名"原文件"
            new_p = op["new_path"]
            old_p = op["old_path"]
            try:
                if os.path.exists(new_p):
                    # 如果原名文件还在(可能上次撤销一半),先删
                    if os.path.exists(old_p):
                        os.remove(old_p)
                    os.rename(new_p, old_p)
                    restored += 1
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("撤销失败", f"{new_p}: {exc}")
        self._set_status(f"已撤销 {restored}/{len(last['ops'])} 个文件")
        # 撤销后清空 rows,引导用户重新添加
        self.rows.clear()
        self._refresh_tree()
        messagebox.showinfo("撤销完成", f"已恢复 {restored} 个文件。请重新「添加 PDF 文件」。")

    def _on_double_click(self, event) -> None:
        """双击姓名/PPS 列可手动修正。"""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        idx = int(row_id)
        col_idx = int(col.replace("#", "")) - 1
        col_key = ("original", "name", "pps", "new_name", "status")[col_idx]
        if col_key not in ("name", "pps"):
            return
        current = self.tree.item(row_id, "values")[col_idx]
        # 弹出一个简单 Entry 编辑器
        editor = tk.Toplevel(self)
        editor.title(f"编辑 {col_key}")
        editor.transient(self)
        editor.geometry("320x90")
        ttk.Label(editor, text=f"{col_key} (当前: {current})").pack(padx=8, pady=(8, 0))
        var = tk.StringVar(value=current)
        entry = ttk.Entry(editor, textvariable=var)
        entry.pack(fill=tk.X, padx=8, pady=4)
        entry.focus_set()
        entry.select_range(0, tk.END)

        def save():
            new_val = var.get().strip()
            self.rows[idx][col_key] = new_val
            # 重新计算新文件名
            if col_key == "name":
                self.rows[idx]["new_name"] = build_new_filename(
                    self.rows[idx]["original_name"], new_val
                ) if new_val else ""
            # 状态修正
            if self.rows[idx]["name"] and self.rows[idx]["pps"]:
                self.rows[idx]["error"] = ""
            self._refresh_tree()
            editor.destroy()

        ttk.Button(editor, text="保存", command=save).pack(pady=4)
        editor.bind("<Return>", lambda _e: save())
        editor.bind("<Escape>", lambda _e: editor.destroy())

    # -----------------------------------------------------------------
    #  辅助
    # -----------------------------------------------------------------
    def _reparse_all(self) -> None:
        """重新对所有 rows 解析姓名和 PPS。"""
        if not self.rows:
            self._refresh_tree()
            return
        self._set_status("正在解析 PDF…")
        self.update_idletasks()
        for r in self.rows:
            pr = parse_pdf(r["path"])
            r["name"] = pr.name
            r["pps"] = pr.pps
            r["error"] = pr.error or ""
            if r["name"]:
                r["new_name"] = build_new_filename(r["original_name"], r["name"])
            else:
                r["new_name"] = ""
        self._refresh_tree()
        ok = sum(1 for r in self.rows if r["name"] and r["pps"])
        fail = len(self.rows) - ok
        self._set_status(f"共 {len(self.rows)} 个 PDF,识别完整 {ok},缺失 {fail}")

    def _refresh_tree(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for i, r in enumerate(self.rows):
            tag = "ok"
            if r.get("encrypted"):
                tag = "encrypted"
                status = "🔒 已加密"
            elif r["name"] and r["pps"]:
                status = "✓ 就绪"
            elif r["name"] and not r["pps"]:
                status = "缺 PPS"
                tag = "fail"
            elif not r["name"] and r["pps"]:
                status = "缺姓名"
                tag = "fail"
            else:
                status = r.get("error") or "未识别"
                tag = "fail"
            self.tree.insert(
                "", tk.END, iid=str(i),
                values=(r["original_name"], r["name"] or "", r["pps"] or "",
                        r["new_name"], status),
                tags=(tag,),
            )

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)


# ============================================================================
#  入口
# ============================================================================

if __name__ == "__main__":
    app = App()
    app.mainloop()
