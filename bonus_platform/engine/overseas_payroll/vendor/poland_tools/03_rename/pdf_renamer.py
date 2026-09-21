#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF文件重命名工具
根据Excel映射表中的"文件名称 -> 工号"对应关系，批量重命名PDF文件。
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import openpyxl
import os
import json
from pathlib import Path
from datetime import datetime

CONFIG_PATH = Path.home() / ".workbuddy" / "pdf_renamer_config.json"

# ---- 常见列名关键词，用于自动识别 ----
NAME_KEYWORDS = ["文件名称", "文件名", "PDF名称", "PDF文件名", "名称", "文件", "filename", "file_name", "name"]
ID_KEYWORDS = ["工号", "员工工号", "编号", "员工编号", "emp_id", "employee_id", "id", "工号ID"]


class PDFRenamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF文件重命名工具 — 按工号重命名")
        self.root.geometry("920x720")
        self.root.minsize(800, 600)

        # ---- 状态 ----
        self.excel_path = tk.StringVar()
        self.sheet_var = tk.StringVar()
        self.name_col_var = tk.StringVar()
        self.id_col_var = tk.StringVar()
        self.match_mode_var = tk.StringVar(value="精确匹配")
        self.keep_ext_var = tk.BooleanVar(value=True)

        self.pdf_files = []        # [(filepath, filename), ...]
        self.excel_data = {}       # {name_normalized: (工号, 原始名称)}
        self.headers = []
        self.sheets = []
        self.preview_map = {}      # {filepath: (new_name, matched, msg)}

        self.load_config()
        self.setup_ui()
        self.log("工具已启动。请选择Excel映射文件并导入PDF文件。")

        if self.excel_path.get() and os.path.exists(self.excel_path.get()):
            self.load_excel()

    # ===================== 配置读写 =====================

    def load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.excel_path.set(cfg.get("excel_path", ""))
                self.name_col_var.set(cfg.get("name_col", ""))
                self.id_col_var.set(cfg.get("id_col", ""))
                raw_mode = cfg.get("match_mode", "精确匹配")
                self.match_mode_var.set("包含匹配" if raw_mode in ("contains", "包含匹配") else "精确匹配")
                self.keep_ext_var.set(cfg.get("keep_ext", True))
        except Exception:
            pass

    def save_config(self):
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            cfg = {
                "excel_path": self.excel_path.get(),
                "name_col": self.name_col_var.get(),
                "id_col": self.id_col_var.get(),
                "match_mode": self.match_mode_var.get(),
                "keep_ext": self.keep_ext_var.get(),
            }
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ===================== UI 构建 =====================

    def setup_ui(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 14, "bold"))
        style.configure("Sub.TLabel", font=("Microsoft YaHei UI", 9))
        style.configure("Action.TButton", font=("Microsoft YaHei UI", 9))
        style.configure("Header.TLabelframe.Label", font=("Microsoft YaHei UI", 10, "bold"))

        # ---- 顶部标题 ----
        top = ttk.Frame(self.root, padding=(12, 8, 12, 4))
        top.pack(fill=tk.X)
        ttk.Label(top, text="PDF文件重命名工具", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(top, text="  根据Excel映射表批量重命名PDF为工号", style="Sub.TLabel").pack(side=tk.LEFT, pady=(6, 0))

        # ---- Excel 配置区 ----
        cfg_frame = ttk.LabelFrame(self.root, text=" Excel映射配置 ", padding=10, style="Header.TLabelframe")
        cfg_frame.pack(fill=tk.X, padx=12, pady=(4, 6))

        row1 = ttk.Frame(cfg_frame)
        row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="Excel文件:", width=10).pack(side=tk.LEFT)
        self.excel_entry = ttk.Entry(row1, textvariable=self.excel_path, state="readonly")
        self.excel_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row1, text="浏览…", command=self.browse_excel, style="Action.TButton").pack(side=tk.LEFT)

        row2 = ttk.Frame(cfg_frame)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="Sheet:", width=10).pack(side=tk.LEFT)
        self.sheet_combo = ttk.Combobox(row2, textvariable=self.sheet_var, state="readonly", width=22)
        self.sheet_combo.pack(side=tk.LEFT, padx=(0, 20))
        self.sheet_combo.bind("<<ComboboxSelected>>", lambda e: self.load_excel(load_sheets_only=False))

        ttk.Label(row2, text="匹配模式:", width=10).pack(side=tk.LEFT)
        self.match_combo = ttk.Combobox(
            row2, textvariable=self.match_mode_var, state="readonly", width=12,
            values=["精确匹配", "包含匹配"],
        )
        self.match_combo.pack(side=tk.LEFT)

        row3 = ttk.Frame(cfg_frame)
        row3.pack(fill=tk.X, pady=3)
        ttk.Label(row3, text="文件名列:", width=10).pack(side=tk.LEFT)
        self.name_col_combo = ttk.Combobox(row3, textvariable=self.name_col_var, state="readonly", width=22)
        self.name_col_combo.pack(side=tk.LEFT, padx=(0, 20))
        self.name_col_combo.bind("<<ComboboxSelected>>", lambda e: self._on_col_changed())
        ttk.Label(row3, text="工号列:", width=10).pack(side=tk.LEFT)
        self.id_col_combo = ttk.Combobox(row3, textvariable=self.id_col_var, state="readonly", width=22)
        self.id_col_combo.pack(side=tk.LEFT)
        self.id_col_combo.bind("<<ComboboxSelected>>", lambda e: self._on_col_changed())

        row4 = ttk.Frame(cfg_frame)
        row4.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(row4, text="保留.pdf扩展名 (重命名为 工号.pdf)", variable=self.keep_ext_var).pack(side=tk.LEFT)
        ttk.Button(row4, text="重新加载Excel", command=self.load_excel, style="Action.TButton").pack(side=tk.RIGHT)

        # ---- 操作按钮区 ----
        btn_frame = ttk.Frame(self.root, padding=(12, 4, 12, 4))
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="导入PDF文件", command=self.import_pdfs, style="Action.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="导入文件夹", command=self.import_folder, style="Action.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="移除选中", command=self.remove_selected, style="Action.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="清空列表", command=self.clear_list, style="Action.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(btn_frame, text="预览匹配", command=self.preview_match, style="Action.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="执行重命名", command=self.execute_rename, style="Action.TButton").pack(side=tk.LEFT)

        # ---- 文件列表区 ----
        list_frame = ttk.LabelFrame(self.root, text=" 文件列表 ", padding=4, style="Header.TLabelframe")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 6))

        columns = ("old_name", "new_name", "status", "note")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("old_name", text="原文件名")
        self.tree.heading("new_name", text="新文件名")
        self.tree.heading("status", text="状态")
        self.tree.heading("note", text="备注")
        self.tree.column("old_name", width=240, minwidth=120)
        self.tree.column("new_name", width=200, minwidth=100)
        self.tree.column("status", width=80, minwidth=60)
        self.tree.column("note", width=250, minwidth=100)

        # 行标签颜色
        self.tree.tag_configure("matched", background="#e8f5e9")
        self.tree.tag_configure("unmatched", background="#fff3e0")
        self.tree.tag_configure("renamed", background="#e3f2fd")
        self.tree.tag_configure("error", background="#ffebee")

        tree_scroll_y = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)

        # ---- 日志区 ----
        log_frame = ttk.LabelFrame(self.root, text=" 操作日志 ", padding=4, style="Header.TLabelframe")
        log_frame.pack(fill=tk.BOTH, padx=12, pady=(0, 6))

        self.log_text = tk.Text(log_frame, height=6, font=("Consolas", 9), state=tk.DISABLED, wrap=tk.WORD)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # ---- 状态栏 ----
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=(8, 2))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ===================== Excel 加载 =====================

    def browse_excel(self):
        path = filedialog.askopenfilename(
            title="选择Excel映射文件",
            filetypes=[("Excel文件", "*.xlsx *.xlsm"), ("所有文件", "*.*")],
        )
        if path:
            self.excel_path.set(path)
            self.load_excel()
            self.save_config()

    def load_excel(self, load_sheets_only=False):
        path = self.excel_path.get()
        if not path or not os.path.exists(path):
            return

        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as e:
            messagebox.showerror("错误", f"无法读取Excel文件:\n{e}")
            return

        # ---- 加载 sheet 列表 ----
        self.sheets = wb.sheetnames
        self.sheet_combo["values"] = self.sheets
        if not self.sheet_var.get() or self.sheet_var.get() not in self.sheets:
            self.sheet_var.set(self.sheets[0])

        if load_sheets_only:
            wb.close()
            return

        # ---- 读取数据 ----
        ws = wb[self.sheet_var.get()]
        rows = list(ws.iter_rows(values_only=True))
        wb.close()

        if not rows:
            messagebox.showwarning("警告", "Excel文件为空。")
            return

        # 第一行作为表头
        self.headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        self.name_col_combo["values"] = self.headers
        self.id_col_combo["values"] = self.headers

        # 自动识别列
        if not self.name_col_var.get() or self.name_col_var.get() not in self.headers:
            self.name_col_var.set(self._auto_detect_col(self.headers, NAME_KEYWORDS) or (self.headers[0] if self.headers else ""))
        if not self.id_col_var.get() or self.id_col_var.get() not in self.headers:
            self.id_col_var.set(self._auto_detect_col(self.headers, ID_KEYWORDS) or (self.headers[1] if len(self.headers) > 1 else ""))

        # 构建映射字典
        self._build_excel_data(rows)
        self.save_config()
        self.log(f"已加载Excel: {os.path.basename(path)}  [Sheet: {self.sheet_var.get()}]  共 {len(self.excel_data)} 条映射")
        self.status_var.set(f"Excel已加载 | 映射 {len(self.excel_data)} 条 | 文件列表 {len(self.pdf_files)} 个")

    def _on_col_changed(self):
        """当用户手动切换文件名列或工号列时，重新构建映射数据"""
        path = self.excel_path.get()
        if not path or not os.path.exists(path):
            return
        if not self.name_col_var.get() or not self.id_col_var.get():
            return
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb[self.sheet_var.get()]
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
            self._build_excel_data(rows)
            self.save_config()
            self.log(f"列已更新 → 文件名列: {self.name_col_var.get()}, 工号列: {self.id_col_var.get()} | 映射 {len(self.excel_data)} 条")
            self.status_var.set(f"映射已更新 | {len(self.excel_data)} 条 | 文件列表 {len(self.pdf_files)} 个")
        except Exception as e:
            self.log(f"更新列失败: {e}")

    def _auto_detect_col(self, headers, keywords):
        for kw in keywords:
            for h in headers:
                if kw.lower() in h.lower():
                    return h
        return ""

    def _build_excel_data(self, rows):
        """从Excel行数据构建 {normalized_name: (工号, 原始名称)} 映射"""
        self.excel_data = {}
        if not rows or len(rows) < 2:
            return
        headers = [str(h).strip() if h is not None else "" for h in rows[0]]
        try:
            name_idx = headers.index(self.name_col_var.get())
            id_idx = headers.index(self.id_col_var.get())
        except ValueError:
            return

        for row in rows[1:]:
            if name_idx >= len(row) or id_idx >= len(row):
                continue
            name_val = row[name_idx]
            id_val = row[id_idx]
            if name_val is None or id_val is None:
                continue
            name_str = str(name_val).strip()
            id_str = str(id_val).strip()
            if not name_str or not id_str:
                continue
            # 同时存储原始名称和去掉扩展名的名称
            norm = self._normalize_name(name_str)
            self.excel_data[norm] = (id_str, name_str)
            # 如果原名称带.pdf，也存一份不带扩展名的
            if name_str.lower().endswith(".pdf"):
                norm_no_ext = self._normalize_name(name_str[:-4])
                if norm_no_ext not in self.excel_data:
                    self.excel_data[norm_no_ext] = (id_str, name_str)

    def _normalize_name(self, name):
        """标准化名称用于匹配：去首尾空格、转小写"""
        return name.strip().lower()

    # ===================== 文件导入 =====================

    def import_pdfs(self):
        files = filedialog.askopenfilenames(
            title="选择PDF文件",
            filetypes=[("PDF文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if files:
            added = 0
            for f in files:
                if self._add_pdf(f):
                    added += 1
            self.refresh_tree()
            self.log(f"导入了 {added} 个PDF文件" + (f"（跳过 {len(files) - added} 个重复）" if added < len(files) else ""))
            self.status_var.set(f"文件列表 {len(self.pdf_files)} 个")

    def import_folder(self):
        folder = filedialog.askdirectory(title="选择包含PDF文件的文件夹")
        if folder:
            added = 0
            for name in os.listdir(folder):
                if name.lower().endswith(".pdf"):
                    if self._add_pdf(os.path.join(folder, name)):
                        added += 1
            self.refresh_tree()
            self.log(f"从文件夹导入了 {added} 个PDF文件")
            self.status_var.set(f"文件列表 {len(self.pdf_files)} 个")

    def _add_pdf(self, filepath):
        """添加PDF到列表，去重。返回是否新增。"""
        filepath = os.path.normpath(filepath)
        for existing_path, _ in self.pdf_files:
            if existing_path == filepath:
                return False
        self.pdf_files.append((filepath, os.path.basename(filepath)))
        return True

    def remove_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        items_to_remove = set()
        for item in selected:
            values = self.tree.item(item, "values")
            if values:
                old_name = values[0]
                for i, (fp, fn) in enumerate(self.pdf_files):
                    if fn == old_name:
                        items_to_remove.add(i)
                        break
        self.pdf_files = [item for i, item in enumerate(self.pdf_files) if i not in items_to_remove]
        self.preview_map = {k: v for k, v in self.preview_map.items() if any(k == fp for fp, _ in self.pdf_files)}
        self.refresh_tree()
        self.status_var.set(f"文件列表 {len(self.pdf_files)} 个")

    def clear_list(self):
        self.pdf_files = []
        self.preview_map = {}
        self.refresh_tree()
        self.status_var.set("文件列表已清空")

    # ===================== 匹配逻辑 =====================

    def _match_pdf(self, filename):
        """
        返回 (工号, matched, msg)
        """
        if not self.excel_data:
            return ("", False, "Excel未加载")

        # 去掉.pdf扩展名
        name_no_ext = filename
        if name_no_ext.lower().endswith(".pdf"):
            name_no_ext = name_no_ext[:-4]
        name_no_ext = name_no_ext.strip()

        norm = self._normalize_name(name_no_ext)

        mode = self.match_mode_var.get()

        # 精确匹配
        if mode == "精确匹配":
            if norm in self.excel_data:
                emp_id, orig = self.excel_data[norm]
                return (emp_id, True, f"匹配: {orig}")
            # 也尝试用完整文件名（带.pdf）匹配
            norm_full = self._normalize_name(filename)
            if norm_full in self.excel_data:
                emp_id, orig = self.excel_data[norm_full]
                return (emp_id, True, f"匹配: {orig}")
            return ("", False, "未找到匹配")

        # 包含匹配
        elif mode == "包含匹配":
            # 先精确
            if norm in self.excel_data:
                emp_id, orig = self.excel_data[norm]
                return (emp_id, True, f"匹配: {orig}")
            # 再包含
            matches = []
            for key, (emp_id, orig) in self.excel_data.items():
                if key and (key in norm or norm in key):
                    matches.append((emp_id, orig))
            if len(matches) == 1:
                return (matches[0][0], True, f"包含匹配: {matches[0][1]}")
            elif len(matches) > 1:
                names = ", ".join(m[1] for m in matches[:3])
                return ("", False, f"匹配到多个: {names}…")
            return ("", False, "未找到匹配")

        return ("", False, "未知匹配模式")

    def preview_match(self):
        if not self.pdf_files:
            messagebox.showinfo("提示", "请先导入PDF文件。")
            return
        if not self.excel_data:
            messagebox.showinfo("提示", "请先加载Excel映射文件。")
            return

        self.preview_map = {}
        matched_count = 0
        for filepath, filename in self.pdf_files:
            emp_id, matched, msg = self._match_pdf(filename)
            if matched:
                ext = ".pdf" if self.keep_ext_var.get() else ""
                new_name = f"{emp_id}{ext}"
                self.preview_map[filepath] = (new_name, True, msg)
                matched_count += 1
            else:
                self.preview_map[filepath] = ("", False, msg)

        self.refresh_tree()
        total = len(self.pdf_files)
        self.log(f"预览完成: 共 {total} 个文件, 匹配 {matched_count}, 未匹配 {total - matched_count}")
        self.status_var.set(f"共 {total} | 匹配 {matched_count} | 未匹配 {total - matched_count}")

    # ===================== 执行重命名 =====================

    def execute_rename(self):
        if not self.pdf_files:
            messagebox.showinfo("提示", "请先导入PDF文件。")
            return
        if not self.excel_data:
            messagebox.showinfo("提示", "请先加载Excel映射文件。")
            return

        # 如果还没预览，先预览
        if not self.preview_map:
            self.preview_match()

        # 统计可重命名的数量
        to_rename = [(fp, fn, self.preview_map.get(fp, ("", False, ""))) for fp, fn in self.pdf_files]
        renamable = [(fp, fn, info) for fp, fn, info in to_rename if info[1]]
        if not renamable:
            messagebox.showinfo("提示", "没有可重命名的文件（所有文件均未匹配到工号）。")
            return

        # 确认对话框
        result = messagebox.askyesno(
            "确认重命名",
            f"即将重命名 {len(renamable)} 个PDF文件。\n"
            f"未匹配的 {len(to_rename) - len(renamable)} 个文件将跳过。\n\n"
            f"确定要执行重命名吗？"
        )
        if not result:
            return

        # 执行重命名
        renamed = 0
        errors = 0
        used_names = {}  # 用于处理重名

        for filepath, filename, (new_name, matched, msg) in renamable:
            if not os.path.exists(filepath):
                self.preview_map[filepath] = ("", False, "文件不存在")
                errors += 1
                continue

            dir_path = os.path.dirname(filepath)
            final_name = new_name

            # 处理重名
            if final_name in used_names:
                base, ext = os.path.splitext(final_name)
                counter = used_names[final_name] + 1
                used_names[final_name] = counter
                final_name = f"{base}_{counter}{ext}"
            else:
                used_names[final_name] = 1

            target_path = os.path.join(dir_path, final_name)

            # 如果目标文件已存在且不是自身
            if os.path.exists(target_path) and os.path.normpath(target_path) != os.path.normpath(filepath):
                base, ext = os.path.splitext(final_name)
                i = 1
                while os.path.exists(os.path.join(dir_path, f"{base}_{i}{ext}")):
                    i += 1
                final_name = f"{base}_{i}{ext}"
                target_path = os.path.join(dir_path, final_name)

            try:
                os.rename(filepath, target_path)
                # 更新列表中的路径和文件名
                for i, (fp, fn) in enumerate(self.pdf_files):
                    if fp == filepath:
                        self.pdf_files[i] = (target_path, final_name)
                        break
                self.preview_map[filepath] = (final_name, True, "已重命名")
                renamed += 1
            except Exception as e:
                self.preview_map[filepath] = ("", False, f"重命名失败: {e}")
                errors += 1

        self.refresh_tree()
        self.log(f"重命名完成: 成功 {renamed}, 失败 {errors}")
        self.status_var.set(f"重命名完成 | 成功 {renamed} | 失败 {errors}")

        if errors > 0:
            messagebox.showwarning("部分完成", f"成功重命名 {renamed} 个文件，{errors} 个文件失败。请查看日志。")
        else:
            messagebox.showinfo("完成", f"成功重命名 {renamed} 个文件。")

    # ===================== Treeview 刷新 =====================

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for filepath, filename in self.pdf_files:
            info = self.preview_map.get(filepath)
            if info:
                new_name, matched, msg = info
                if msg == "已重命名":
                    status = "已重命名"
                    tag = "renamed"
                elif matched:
                    status = "已匹配"
                    tag = "matched"
                else:
                    status = "未匹配"
                    tag = "unmatched"
                if msg.startswith("重命名失败"):
                    status = "失败"
                    tag = "error"
            else:
                new_name = ""
                status = "待匹配"
                tag = ""
                msg = ""

            self.tree.insert("", tk.END, values=(filename, new_name, status, msg), tags=(tag,) if tag else ())

    # ===================== 日志 =====================

    def log(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)


def main():
    root = tk.Tk()
    app = PDFRenamerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
