# -*- coding: utf-8 -*-
"""
文件加密工具
根据 Excel 表中文件名对应的 Pesel 数字作为密码，批量加密 PDF / xlsx / xls 文件。
支持拖拽导入和文件选择导入。
"""

import os
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import openpyxl
from pypdf import PdfReader, PdfWriter
import msoffcrypto
import xlrd

# 尝试导入拖拽支持
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False


DEFAULT_EXCEL = r"D:\其他\Documents\Downloads\波兰员工工资单文件名列表 - 副本.xlsx"

SUPPORTED_EXTS = {".pdf", ".xlsx", ".xls"}


class FileEncryptorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("文件加密工具 — 波兰员工工资单")
        self.root.geometry("880x680")
        self.root.minsize(760, 580)

        # ---- 数据 ----
        self.excel_path = tk.StringVar(value=DEFAULT_EXCEL)
        self.output_dir = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Desktop", "加密文件输出")
        )
        self.password_map = {}        # {filename_lower: pesel_str}
        self.excel_row_count = 0
        self.file_items = []          # [{path, name, password, matched, status, result, file_type}]

        self._build_ui()
        self._auto_load_excel()

    # ==================== UI 构建 ====================

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # 颜色常量
        self.COLOR_BG = "#f5f6fa"
        self.COLOR_DROP = "#eef1f8"
        self.COLOR_DROP_HOVER = "#e2e8f5"
        self.COLOR_ACCENT = "#3b6fd4"
        self.COLOR_OK = "#27ae60"
        self.COLOR_WARN = "#e67e22"
        self.COLOR_ERR = "#e74c3c"

        self.root.configure(bg=self.COLOR_BG)

        # ---- 顶部标题 ----
        title_frame = tk.Frame(self.root, bg=self.COLOR_ACCENT, height=52)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)
        tk.Label(
            title_frame, text="🔒  文件加密工具",
            font=("Microsoft YaHei UI", 16, "bold"),
            fg="white", bg=self.COLOR_ACCENT
        ).pack(side="left", padx=16)
        tk.Label(
            title_frame, text="根据 Excel 中 Pesel 号码加密 PDF / Excel 文件",
            font=("Microsoft YaHei UI", 10),
            fg="#d6e0f5", bg=self.COLOR_ACCENT
        ).pack(side="left", padx=4)

        # ---- 主容器 ----
        main = tk.Frame(self.root, bg=self.COLOR_BG)
        main.pack(fill="both", expand=True, padx=16, pady=10)

        # ---- Excel 路径区 ----
        excel_frame = tk.LabelFrame(main, text=" 密码表 (Excel) ", font=("Microsoft YaHei UI", 10), bg=self.COLOR_BG, fg="#333")
        excel_frame.pack(fill="x", pady=(0, 8))

        row = tk.Frame(excel_frame, bg=self.COLOR_BG)
        row.pack(fill="x", padx=10, pady=8)
        tk.Entry(row, textvariable=self.excel_path, font=("Consolas", 9)).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="浏览…", command=self._browse_excel, width=8,
                  font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(6, 0))
        tk.Button(row, text="重新加载", command=self._auto_load_excel, width=10,
                  font=("Microsoft YaHei UI", 9), bg=self.COLOR_ACCENT, fg="white").pack(side="left", padx=(6, 0))

        self.excel_status_label = tk.Label(excel_frame, text="正在加载…", font=("Microsoft YaHei UI", 9),
                                           bg=self.COLOR_BG, fg="#666")
        self.excel_status_label.pack(anchor="w", padx=12, pady=(0, 6))

        # ---- 拖拽区 ----
        drop_frame = tk.Frame(main, bg=self.COLOR_BG)
        drop_frame.pack(fill="x", pady=(0, 8))

        self.drop_label = tk.Label(
            drop_frame,
            text="📥  将 PDF / xlsx / xls 文件拖拽到此处\n或点击下方「导入文件」按钮选择文件",
            font=("Microsoft YaHei UI", 11),
            bg=self.COLOR_DROP, fg="#5a6a8a", relief="groove", bd=2,
            height=3, cursor="hand2"
        )
        self.drop_label.pack(fill="x")
        self.drop_label.bind("<Button-1>", lambda e: self._import_files_dialog())
        self.drop_label.bind("<Enter>", lambda e: self.drop_label.config(bg=self.COLOR_DROP_HOVER))
        self.drop_label.bind("<Leave>", lambda e: self.drop_label.config(bg=self.COLOR_DROP))

        if DND_AVAILABLE:
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind("<<Drop>>", self._on_drop)
            self.drop_label.dnd_bind("<<DragEnter>>", self._on_drag_enter)
            self.drop_label.dnd_bind("<<DragLeave>>", self._on_drag_leave)

        # ---- 文件列表区 ----
        list_frame = tk.LabelFrame(main, text=" 文件列表 ", font=("Microsoft YaHei UI", 10), bg=self.COLOR_BG, fg="#333")
        list_frame.pack(fill="both", expand=True, pady=(0, 8))

        columns = ("idx", "name", "type", "password", "match", "status")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=10)
        self.tree.heading("idx", text="#")
        self.tree.heading("name", text="文件名")
        self.tree.heading("type", text="类型")
        self.tree.heading("password", text="密码(Pesel)")
        self.tree.heading("match", text="匹配")
        self.tree.heading("status", text="状态")
        self.tree.column("idx", width=40, anchor="center", stretch=False)
        self.tree.column("name", width=300, anchor="w", stretch=True)
        self.tree.column("type", width=60, anchor="center", stretch=False)
        self.tree.column("password", width=140, anchor="center", stretch=False)
        self.tree.column("match", width=50, anchor="center", stretch=False)
        self.tree.column("status", width=140, anchor="center", stretch=False)

        # 行标签用于着色
        self.tree.tag_configure("ok", foreground=self.COLOR_OK)
        self.tree.tag_configure("warn", foreground=self.COLOR_WARN)
        self.tree.tag_configure("err", foreground=self.COLOR_ERR)
        self.tree.tag_configure("done", foreground=self.COLOR_OK, background="#eafaf1")

        tree_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        tree_scroll.pack(side="right", fill="y", pady=8, padx=(0, 8))

        # ---- 输出目录区 ----
        out_frame = tk.Frame(main, bg=self.COLOR_BG)
        out_frame.pack(fill="x", pady=(0, 8))
        tk.Label(out_frame, text="输出目录:", font=("Microsoft YaHei UI", 9), bg=self.COLOR_BG).pack(side="left")
        tk.Entry(out_frame, textvariable=self.output_dir, font=("Consolas", 9)).pack(side="left", fill="x", expand=True, padx=6)
        tk.Button(out_frame, text="浏览…", command=self._browse_output, width=8,
                  font=("Microsoft YaHei UI", 9)).pack(side="left")

        # ---- 底部操作区 ----
        btn_frame = tk.Frame(main, bg=self.COLOR_BG)
        btn_frame.pack(fill="x", pady=(0, 4))

        tk.Button(btn_frame, text="📄 导入文件", command=self._import_files_dialog, width=14,
                  font=("Microsoft YaHei UI", 10, "bold"), bg=self.COLOR_ACCENT, fg="white",
                  relief="flat", padx=8, pady=4).pack(side="left")
        tk.Button(btn_frame, text="🗑 清空列表", command=self._clear_list, width=12,
                  font=("Microsoft YaHei UI", 10), relief="flat", bg="#b0bec5", fg="white",
                  padx=8, pady=4).pack(side="left", padx=6)
        tk.Button(btn_frame, text="🔐 加密全部", command=self._encrypt_all, width=14,
                  font=("Microsoft YaHei UI", 10, "bold"), relief="flat", bg=self.COLOR_OK, fg="white",
                  padx=8, pady=4).pack(side="right")

        # 进度条
        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.pack(fill="x", pady=(6, 2))
        self.progress_label = tk.Label(main, text="就绪", font=("Microsoft YaHei UI", 9),
                                       bg=self.COLOR_BG, fg="#666")
        self.progress_label.pack(anchor="w")

        # 状态栏
        self.status_bar = tk.Label(self.root, text="就绪  |  拖拽 PDF / Excel 文件到上方区域开始",
                                   font=("Microsoft YaHei UI", 9), bg="#dfe4ea", fg="#555",
                                   anchor="w", padx=12, pady=3)
        self.status_bar.pack(fill="x", side="bottom")

    # ==================== Excel 加载 ====================

    def _auto_load_excel(self):
        path = self.excel_path.get().strip()
        if not path or not os.path.isfile(path):
            self.excel_status_label.config(text="⚠ Excel 文件不存在，请点击「浏览」选择", foreground=self.COLOR_ERR)
            self.password_map.clear()
            self.excel_row_count = 0
            return

        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb[wb.sheetnames[0]]

            rows = list(ws.iter_rows(values_only=True))
            wb.close()

            if not rows:
                self.excel_status_label.config(text="⚠ Excel 为空", foreground=self.COLOR_ERR)
                return

            header = rows[0]
            name_col = None
            pwd_col = None
            for i, val in enumerate(header):
                if val is None:
                    continue
                sval = str(val).strip().lower()
                if name_col is None and any(k in sval for k in ("文件名", "filename", "文件")):
                    name_col = i
                if pwd_col is None and any(k in sval for k in ("pesel", "密码", "password", "数字")):
                    pwd_col = i

            if name_col is None:
                name_col = 1
            if pwd_col is None:
                pwd_col = 2

            self.password_map.clear()
            for row in rows[1:]:
                if row is None:
                    continue
                fname = row[name_col] if name_col < len(row) else None
                pesel = row[pwd_col] if pwd_col < len(row) else None
                if fname is None or pesel is None:
                    continue
                fname_str = str(fname).strip()
                pesel_str = self._normalize_pesel(pesel)
                if not fname_str or not pesel_str:
                    continue
                self.password_map[fname_str.lower()] = pesel_str
                name_no_ext = os.path.splitext(fname_str)[0].lower()
                if name_no_ext not in self.password_map:
                    self.password_map[name_no_ext] = pesel_str

            self.excel_row_count = len(self.password_map) // 2
            self.excel_status_label.config(
                text=f"✓ 已加载 {self.excel_row_count} 条记录  |  文件名→Pesel 映射就绪",
                foreground=self.COLOR_OK
            )
            self.status_bar.config(text=f"Excel 已加载: {self.excel_row_count} 条密码记录")

        except Exception as e:
            self.excel_status_label.config(text=f"✗ 加载失败: {e}", foreground=self.COLOR_ERR)

    def _normalize_pesel(self, value):
        if value is None:
            return ""
        if isinstance(value, float):
            if value == int(value):
                return str(int(value))
            return str(value)
        if isinstance(value, int):
            return str(value)
        s = str(value).strip()
        if s.endswith(".0"):
            s = s[:-2]
        return s

    # ==================== 文件导入 ====================

    def _browse_excel(self):
        path = filedialog.askopenfilename(
            title="选择 Excel 密码表",
            filetypes=[("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")],
            initialdir=os.path.dirname(self.excel_path.get()) or os.path.expanduser("~")
        )
        if path:
            self.excel_path.set(path)
            self._auto_load_excel()

    def _browse_output(self):
        d = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir.get() or os.path.expanduser("~"))
        if d:
            self.output_dir.set(d)

    def _import_files_dialog(self):
        files = filedialog.askopenfilenames(
            title="选择文件",
            filetypes=[
                ("所有支持的文件", "*.pdf *.PDF *.xlsx *.xls"),
                ("PDF 文件", "*.pdf *.PDF"),
                ("Excel 文件", "*.xlsx *.xls"),
                ("所有文件", "*.*")
            ]
        )
        if files:
            self._add_files(files)

    def _on_drop(self, event):
        self.drop_label.config(bg=self.COLOR_DROP)
        raw = event.data
        files = self.root.tk.splitlist(raw)
        valid_files = []
        for f in files:
            f = f.strip("{}")
            if os.path.isfile(f):
                ext = os.path.splitext(f)[1].lower()
                if ext in SUPPORTED_EXTS:
                    valid_files.append(f)
            elif os.path.isdir(f):
                for item in os.listdir(f):
                    if os.path.splitext(item)[1].lower() in SUPPORTED_EXTS:
                        valid_files.append(os.path.join(f, item))
        if valid_files:
            self._add_files(valid_files)

    def _on_drag_enter(self, event):
        self.drop_label.config(bg=self.COLOR_DROP_HOVER)

    def _on_drag_leave(self, event):
        self.drop_label.config(bg=self.COLOR_DROP)

    def _add_files(self, file_paths):
        existing = {item["path"].lower() for item in self.file_items}
        added = 0
        for fp in file_paths:
            if fp.lower() in existing:
                continue
            fname = os.path.basename(fp)
            pwd = self._lookup_password(fname)
            ftype = self._get_file_type(fname)
            item = {
                "path": fp,
                "name": fname,
                "password": pwd,
                "matched": pwd is not None,
                "status": "已匹配" if pwd else "未找到密码",
                "result": "",
                "file_type": ftype
            }
            self.file_items.append(item)
            existing.add(fp.lower())
            added += 1
        self._refresh_tree()
        matched_count = sum(1 for i in self.file_items if i['matched'])
        self.status_bar.config(text=f"已导入 {added} 个文件，共 {len(self.file_items)} 个  |  匹配 {matched_count} 个")

    def _get_file_type(self, filename):
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".pdf":
            return "PDF"
        elif ext == ".xlsx":
            return "xlsx"
        elif ext == ".xls":
            return "xls"
        return "?"

    def _lookup_password(self, filename):
        fname_lower = filename.lower()
        if fname_lower in self.password_map:
            return self.password_map[fname_lower]
        name_no_ext = os.path.splitext(fname_lower)[0]
        if name_no_ext in self.password_map:
            return self.password_map[name_no_ext]
        return None

    def _clear_list(self):
        if not self.file_items:
            return
        if messagebox.askyesno("确认", "确定要清空文件列表吗？"):
            self.file_items.clear()
            self._refresh_tree()
            self.progress["value"] = 0
            self.progress_label.config(text="就绪")
            self.status_bar.config(text="列表已清空")

    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, item in enumerate(self.file_items):
            pwd_display = item["password"] if item["password"] else "—"
            match_text = "✓" if item["matched"] else "✗"
            status_text = item["result"] if item["result"] else item["status"]

            tag = ""
            if item["result"]:
                if "成功" in item["result"]:
                    tag = "done"
                elif "失败" in item["result"] or "错误" in item["result"]:
                    tag = "err"
            elif not item["matched"]:
                tag = "warn"
            elif item["matched"]:
                tag = "ok"

            self.tree.insert("", "end", iid=str(i), values=(
                i + 1,
                item["name"],
                item["file_type"],
                pwd_display,
                match_text,
                status_text
            ), tags=(tag,))

    # ==================== 加密 ====================

    def _encrypt_all(self):
        if not self.file_items:
            messagebox.showinfo("提示", "请先导入文件。")
            return

        matched = [item for item in self.file_items if item["matched"]]
        if not matched:
            messagebox.showwarning("无匹配", "没有找到匹配的密码，请检查 Excel 文件和文件名是否对应。")
            return

        out_dir = self.output_dir.get().strip()
        if not out_dir:
            messagebox.showwarning("输出目录", "请先选择输出目录。")
            return
        os.makedirs(out_dir, exist_ok=True)

        unmatch_count = len(self.file_items) - len(matched)
        msg = f"即将加密 {len(matched)} 个文件"
        if unmatch_count > 0:
            msg += f"\n（{unmatch_count} 个未匹配密码将被跳过）"
        msg += f"\n输出目录: {out_dir}"
        msg += "\n\n注意: xls 文件将转为 xlsx 格式后加密"
        if not messagebox.askyesno("确认加密", msg):
            return

        self._set_buttons_state("disabled")
        self.progress["maximum"] = len(matched)
        self.progress["value"] = 0

        threading.Thread(target=self._encrypt_worker, args=(matched, out_dir), daemon=True).start()

    def _encrypt_worker(self, items, out_dir):
        total = len(items)
        success = 0
        fail = 0

        for i, item in enumerate(items):
            try:
                self.root.after(0, lambda i=i, item=item: self.progress_label.config(
                    text=f"正在加密 ({i+1}/{total}): {item['name']}"))

                ftype = item["file_type"]
                pwd = item["password"]

                if ftype == "PDF":
                    self._encrypt_pdf(item, pwd, out_dir)
                elif ftype == "xlsx":
                    self._encrypt_xlsx(item, pwd, out_dir)
                elif ftype == "xls":
                    self._encrypt_xls(item, pwd, out_dir)
                else:
                    raise ValueError(f"不支持的文件类型: {ftype}")

                item["result"] = "✓ 加密成功"
                item["status"] = "✓ 加密成功"
                success += 1
                self.root.after(0, lambda idx=self.file_items.index(item): self._update_tree_row(idx, "done"))

            except Exception as e:
                item["result"] = f"✗ 失败: {e}"
                item["status"] = "✗ 失败"
                fail += 1
                self.root.after(0, lambda idx=self.file_items.index(item): self._update_tree_row(idx, "err"))

            self.root.after(0, lambda v=i + 1: self.progress.configure(value=v))

        summary = f"完成！成功 {success}，失败 {fail}，共 {total} 个文件"
        self.root.after(0, lambda: self.progress_label.config(text=summary))
        self.root.after(0, lambda: self.status_bar.config(text=summary))
        self.root.after(0, lambda: self._set_buttons_state("normal"))
        if fail == 0:
            self.root.after(0, lambda: messagebox.showinfo("完成", f"全部加密成功！\n{success} 个文件已保存到:\n{out_dir}"))
        else:
            self.root.after(0, lambda: messagebox.showwarning("完成(有失败)", f"{summary}\n输出目录: {out_dir}"))

    def _encrypt_pdf(self, item, pwd, out_dir):
        """加密 PDF 文件"""
        reader = PdfReader(item["path"])

        if reader.is_encrypted:
            item["result"] = "跳过(已加密)"
            item["status"] = "跳过(已加密)"
            self.root.after(0, lambda idx=self.file_items.index(item): self._update_tree_row(idx, "warn"))
            return

        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        writer.encrypt(user_password=pwd, owner_password=pwd, use_128bit=True)

        out_path = os.path.join(out_dir, item["name"])
        if os.path.exists(out_path):
            base, ext = os.path.splitext(out_path)
            out_path = f"{base}_encrypted{ext}"

        with open(out_path, "wb") as f:
            writer.write(f)

    def _encrypt_xlsx(self, item, pwd, out_dir):
        """加密 xlsx 文件"""
        with open(item["path"], "rb") as f:
            office_file = msoffcrypto.OfficeFile(f)

            # 检查是否已加密
            if office_file.is_encrypted():
                item["result"] = "跳过(已加密)"
                item["status"] = "跳过(已加密)"
                self.root.after(0, lambda idx=self.file_items.index(item): self._update_tree_row(idx, "warn"))
                return

            out_path = os.path.join(out_dir, item["name"])
            if os.path.exists(out_path):
                base, ext = os.path.splitext(out_path)
                out_path = f"{base}_encrypted{ext}"

            with open(out_path, "wb") as out:
                office_file.encrypt(pwd, out)

    def _encrypt_xls(self, item, pwd, out_dir):
        """加密 xls 文件: 先转为 xlsx，再用 msoffcrypto 加密"""
        # 1. 用 xlrd 读取 xls
        book = xlrd.open_workbook(item["path"])
        # 2. 用 openpyxl 写入临时 xlsx
        wb = openpyxl.Workbook()
        # 移除默认创建的空 sheet
        wb.remove(wb.active)

        for sheet_idx in range(book.nsheets):
            sheet = book.sheet_by_index(sheet_idx)
            ws = wb.create_sheet(title=sheet.name)
            for row_idx in range(sheet.nrows):
                for col_idx in range(sheet.ncols):
                    cell_value = sheet.cell_value(row_idx, col_idx)
                    # 处理日期类型
                    if sheet.cell_type(row_idx, col_idx) == xlrd.XL_CELL_DATE:
                        try:
                            date_tuple = xlrd.xldate_as_tuple(cell_value, book.datemode)
                            import datetime
                            cell_value = datetime.datetime(*date_tuple)
                        except Exception:
                            pass
                    ws.cell(row=row_idx + 1, column=col_idx + 1, value=cell_value)

        # 如果没有 sheet，创建一个空的
        if not wb.sheetnames:
            wb.create_sheet(title="Sheet1")

        # 保存到临时文件
        tmp_xlsx = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        tmp_xlsx_path = tmp_xlsx.name
        tmp_xlsx.close()
        wb.save(tmp_xlsx_path)
        wb.close()

        try:
            # 3. 用 msoffcrypto 加密临时 xlsx
            with open(tmp_xlsx_path, "rb") as f:
                office_file = msoffcrypto.OfficeFile(f)

                # 输出文件名: 原文件名 .xls → .xlsx
                base_name = os.path.splitext(item["name"])[0]
                out_name = base_name + ".xlsx"
                out_path = os.path.join(out_dir, out_name)
                if os.path.exists(out_path):
                    out_path = os.path.join(out_dir, f"{base_name}_encrypted.xlsx")

                with open(out_path, "wb") as out:
                    office_file.encrypt(pwd, out)
        finally:
            # 清理临时文件
            if os.path.exists(tmp_xlsx_path):
                os.remove(tmp_xlsx_path)

    def _update_tree_row(self, idx, tag):
        try:
            item = self.file_items[idx]
            self.tree.item(str(idx), values=(
                idx + 1,
                item["name"],
                item["file_type"],
                item["password"] if item["password"] else "—",
                "✓" if item["matched"] else "✗",
                item["result"] if item["result"] else item["status"]
            ), tags=(tag,))
        except Exception:
            pass

    def _set_buttons_state(self, state):
        for child in self.root.winfo_children():
            self._recursive_set_buttons(child, state)

    def _recursive_set_buttons(self, widget, state):
        for child in widget.winfo_children():
            if isinstance(child, tk.Button):
                child.config(state=state)
            self._recursive_set_buttons(child, state)


# ==================== 启动 ====================

def main():
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = FileEncryptorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
