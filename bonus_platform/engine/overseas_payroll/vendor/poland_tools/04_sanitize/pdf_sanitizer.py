#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF工资单隐私处理工具
删除PDF中包含指定关键词的整行，将剩余内容渲染为PNG并裁剪到内容区域。
适用于波兰 payroll PDF（移除 Pracownik、Data wystawienia 等敏感行）。
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import fitz
import os
import re
import json
from pathlib import Path
from PIL import Image
import numpy as np
from datetime import datetime

CONFIG_PATH = Path.home() / ".workbuddy" / "pdf_sanitizer_config.json"

DEFAULT_KEYWORDS = "Pracownik:\nData wystawienia:\npracownika\nPESEL:+11"

# 关键词语法: "关键词+N" 表示定向涂白（只涂白关键词span + 右侧N位数字span），不删整行
# 例如 "PESEL:+11" 表示涂白 "PESEL:" 标签和右侧的11位号码
TARGETED_PATTERN = re.compile(r'^(.+)\+(\d+)$')


class PDFSanitizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF工资单隐私处理工具")
        self.root.geometry("880x700")
        self.root.minsize(780, 580)

        # ---- 状态 ----
        self.output_dir = tk.StringVar()
        self.keywords_text = tk.StringVar(value=DEFAULT_KEYWORDS)
        self.dpi_var = tk.StringVar(value="200")
        self.crop_margin_var = tk.StringVar(value="10")
        self.pdf_files = []  # [(filepath, filename), ...]

        self.load_config()
        self.setup_ui()
        self.log("工具已启动。请选择输出文件夹并导入PDF文件。")

    # ===================== 配置读写 =====================

    def load_config(self):
        try:
            if CONFIG_PATH.exists():
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.output_dir.set(cfg.get("output_dir", ""))
                self.keywords_text.set(cfg.get("keywords", DEFAULT_KEYWORDS))
                self.dpi_var.set(str(cfg.get("dpi", 200)))
                self.crop_margin_var.set(str(cfg.get("margin", 10)))
        except Exception:
            pass

    def save_config(self):
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            cfg = {
                "output_dir": self.output_dir.get(),
                "keywords": self.keywords_text.get(),
                "dpi": int(self.dpi_var.get() or 200),
                "margin": int(self.crop_margin_var.get() or 10),
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
        ttk.Label(top, text="PDF工资单隐私处理工具", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(top, text="  删除敏感行并保存为PNG", style="Sub.TLabel").pack(side=tk.LEFT, pady=(6, 0))

        # ---- 配置区 ----
        cfg_frame = ttk.LabelFrame(self.root, text=" 处理配置 ", padding=10, style="Header.TLabelframe")
        cfg_frame.pack(fill=tk.X, padx=12, pady=(4, 6))

        row1 = ttk.Frame(cfg_frame)
        row1.pack(fill=tk.X, pady=3)
        ttk.Label(row1, text="输出文件夹:", width=12).pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.output_dir, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row1, text="浏览…", command=self.browse_output_dir, style="Action.TButton").pack(side=tk.LEFT)

        row2 = ttk.Frame(cfg_frame)
        row2.pack(fill=tk.X, pady=3)
        ttk.Label(row2, text="删除关键词:", width=12).pack(side=tk.LEFT, anchor=tk.N)
        self.keywords_entry = tk.Text(row2, height=5, font=("Microsoft YaHei UI", 9), wrap=tk.WORD)
        self.keywords_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self.keywords_entry.insert(tk.END, self.keywords_text.get())
        ttk.Label(row2, text="每行一个关键词\n普通关键词: 删除整行\n\"关键词+N\": 涂白关键词+右侧N位数字\n例: PESEL:+11", foreground="#888780", justify=tk.LEFT).pack(side=tk.LEFT, anchor=tk.NW)

        row3 = ttk.Frame(cfg_frame)
        row3.pack(fill=tk.X, pady=3)
        ttk.Label(row3, text="输出DPI:", width=12).pack(side=tk.LEFT)
        ttk.Combobox(row3, textvariable=self.dpi_var, state="readonly", width=10, values=["150", "200", "300", "400"]).pack(side=tk.LEFT, padx=(0, 20))
        ttk.Label(row3, text="裁剪边距(px):", width=12).pack(side=tk.LEFT)
        ttk.Combobox(row3, textvariable=self.crop_margin_var, state="readonly", width=10, values=["0", "5", "10", "15", "20"]).pack(side=tk.LEFT)

        # ---- 操作按钮区 ----
        btn_frame = ttk.Frame(self.root, padding=(12, 4, 12, 4))
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="导入PDF文件", command=self.import_pdfs, style="Action.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="导入文件夹", command=self.import_folder, style="Action.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="移除选中", command=self.remove_selected, style="Action.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="清空列表", command=self.clear_list, style="Action.TButton").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Separator(btn_frame, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(btn_frame, text="开始处理", command=self.process_all, style="Action.TButton").pack(side=tk.LEFT)

        # ---- 文件列表区 ----
        list_frame = ttk.LabelFrame(self.root, text=" 文件列表 ", padding=4, style="Header.TLabelframe")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 6))

        columns = ("file_name", "status", "output_path")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("file_name", text="PDF文件名")
        self.tree.heading("status", text="状态")
        self.tree.heading("output_path", text="输出PNG路径")
        self.tree.column("file_name", width=220, minwidth=120)
        self.tree.column("status", width=100, minwidth=80)
        self.tree.column("output_path", width=420, minwidth=150)

        self.tree.tag_configure("done", background="#e8f5e9")
        self.tree.tag_configure("error", background="#ffebee")
        self.tree.tag_configure("pending", background="")

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

    # ===================== 文件导入 =====================

    def browse_output_dir(self):
        folder = filedialog.askdirectory(title="选择PNG输出文件夹")
        if folder:
            self.output_dir.set(folder)
            self.save_config()

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
            self.log(f"导入了 {added} 个PDF文件")
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
                file_name = values[0]
                for i, (fp, fn) in enumerate(self.pdf_files):
                    if fn == file_name:
                        items_to_remove.add(i)
                        break
        self.pdf_files = [item for i, item in enumerate(self.pdf_files) if i not in items_to_remove]
        self.refresh_tree()
        self.status_var.set(f"文件列表 {len(self.pdf_files)} 个")

    def clear_list(self):
        self.pdf_files = []
        self.refresh_tree()
        self.status_var.set("文件列表已清空")

    def refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for filepath, filename in self.pdf_files:
            self.tree.insert("", tk.END, values=(filename, "待处理", ""), tags=("pending",))

    # ===================== 核心处理逻辑 =====================

    def get_keywords(self):
        """从文本框读取关键词列表"""
        text = self.keywords_entry.get("1.0", tk.END).strip()
        keywords = [line.strip() for line in text.splitlines() if line.strip()]
        return keywords

    def process_all(self):
        if not self.pdf_files:
            messagebox.showinfo("提示", "请先导入PDF文件。")
            return

        output_dir = self.output_dir.get()
        if not output_dir:
            messagebox.showinfo("提示", "请先选择输出文件夹。")
            return

        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                messagebox.showerror("错误", f"无法创建输出文件夹:\n{e}")
                return

        keywords = self.get_keywords()
        if not keywords:
            messagebox.showinfo("提示", "请至少输入一个关键词。")
            return

        # 保存当前关键词
        self.keywords_text.set(self.keywords_entry.get("1.0", tk.END))
        self.save_config()

        try:
            dpi = int(self.dpi_var.get())
            margin = int(self.crop_margin_var.get())
        except ValueError:
            messagebox.showerror("错误", "DPI和边距必须是整数。")
            return

        total = len(self.pdf_files)
        success = 0
        failed = 0

        for idx, (filepath, filename) in enumerate(self.pdf_files, start=1):
            self.status_var.set(f"处理中 {idx}/{total}: {filename}")
            self.root.update_idletasks()

            try:
                out_path = self.process_single_pdf(filepath, output_dir, keywords, dpi, margin)
                self.update_tree_status(filename, "完成", out_path)
                self.log(f"完成: {filename} -> {os.path.basename(out_path)}")
                success += 1
            except Exception as e:
                self.update_tree_status(filename, "失败", str(e))
                self.log(f"失败: {filename} - {e}")
                failed += 1

        self.status_var.set(f"处理完成 | 成功 {success} | 失败 {failed}")
        if failed > 0:
            messagebox.showwarning("部分完成", f"成功 {success} 个，失败 {failed} 个。请查看日志。")
        else:
            messagebox.showinfo("完成", f"成功处理 {success} 个PDF文件。")

    def parse_keywords(self, raw_keywords):
        """解析关键词列表，区分普通关键词和定向涂白关键词
        返回: (line_keywords, targeted_keywords)
        - line_keywords: [(keyword, ), ...] 删除整行
        - targeted_keywords: [(keyword, digit_count), ...] 定向涂白关键词+右侧N位数字
        """
        line_keywords = []
        targeted_keywords = []
        for kw in raw_keywords:
            if not kw:
                continue
            m = TARGETED_PATTERN.match(kw)
            if m:
                targeted_keywords.append((m.group(1), int(m.group(2))))
            else:
                line_keywords.append(kw)
        return line_keywords, targeted_keywords

    def process_single_pdf(self, pdf_path, output_dir, keywords, dpi, margin):
        """处理单个PDF文件，返回输出PNG路径"""
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            raise ValueError("PDF文件为空")

        if len(doc) > 1:
            self.log(f"警告: {os.path.basename(pdf_path)} 包含多页，仅处理第一页")

        page = doc[0]

        # 获取所有文本 span
        blocks = page.get_text("dict")["blocks"]
        spans = []
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if text:
                            spans.append({"text": text, "bbox": span["bbox"]})

        # 解析关键词
        line_keywords, targeted_keywords = self.parse_keywords(keywords)

        # ---- 1. 整行删除关键词 ----
        redact_rects = []
        for kw in line_keywords:
            kw_lower = kw.lower()
            matched_spans = [s for s in spans if kw_lower in s["text"].lower()]
            for m in matched_spans:
                bbox = m["bbox"]
                line_height = bbox[3] - bbox[1]
                rect = fitz.Rect(
                    0,
                    bbox[1] - line_height * 0.2,
                    page.rect.width,
                    bbox[3] + line_height * 0.2
                )
                redact_rects.append(rect)

        # ---- 2. 定向涂白关键词（只涂白关键词span + 右侧N位数字span） ----
        digit_pattern = re.compile(r'^\d[\d\s\-]*\d$')
        for kw, digit_count in targeted_keywords:
            # 去除尾部冒号/空格，使匹配更灵活（"PESEL:" → "PESEL"）
            kw_search = kw.rstrip(":：\u00a0 ")
            kw_lower = kw_search.lower()
            matched_spans = [s for s in spans if kw_lower in s["text"].lower()]
            for m in matched_spans:
                bbox = m["bbox"]
                line_height = bbox[3] - bbox[1]
                y1, y3 = bbox[1], bbox[3]

                # 先涂白关键词本身
                kw_rect = fitz.Rect(
                    bbox[0] - 2,
                    y1 - line_height * 0.15,
                    bbox[2] + 2,
                    y3 + line_height * 0.15
                )
                redact_rects.append(kw_rect)

                # 在同一视觉行上，找到关键词右侧的N位数字span
                same_line = [s for s in spans
                             if abs(s["bbox"][1] - y1) < line_height * 1.5
                             and abs(s["bbox"][3] - y3) < line_height * 1.5
                             and s["bbox"][0] > bbox[2]]

                # 匹配: 纯数字(允许空格/连字符)且去除后恰好为N位
                found_number = False
                for s in same_line:
                    clean_digits = s["text"].replace(" ", "").replace("\u00a0", "").replace("-", "")
                    if digit_pattern.match(s["text"]) and len(clean_digits) == digit_count:
                        num_rect = fitz.Rect(
                            s["bbox"][0] - 2,
                            s["bbox"][1] - line_height * 0.15,
                            s["bbox"][2] + 2,
                            s["bbox"][3] + line_height * 0.15
                        )
                        redact_rects.append(num_rect)
                        self.log(f"  定向涂白: \"{s['text']}\" (右侧{digit_count}位数字)")
                        found_number = True
                        break  # 只取第一个匹配的N位数字

                # 回退: 关键词span自身可能包含N位数字（如"PESEL: 94011316115"在同一span）
                if not found_number:
                    num_in_text = re.search(r'\d{' + str(digit_count) + r'}', m["text"])
                    if num_in_text:
                        num_str = num_in_text.group()
                        search_rects = page.search_for(num_str)
                        if search_rects:
                            for sr in search_rects:
                                if abs(sr.y0 - y1) < line_height * 2 and sr.x0 >= bbox[0]:
                                    num_rect = fitz.Rect(
                                        sr.x0 - 2, sr.y0 - 2,
                                        sr.x1 + 2, sr.y1 + 2
                                    )
                                    redact_rects.append(num_rect)
                                    self.log(f"  定向涂白: \"{num_str}\" (span内{digit_count}位数字)")
                                    found_number = True
                                    break

        # 合并重叠的删除区域
        redact_rects = self.merge_rects(redact_rects)

        # 应用删除（白色覆盖）
        for rect in redact_rects:
            page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()

        # 渲染为图片
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        temp_path = os.path.join(output_dir, "_temp_render.png")
        pix.save(temp_path)
        doc.close()

        # 裁剪到内容区域
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        out_path = os.path.join(output_dir, f"{base_name}.png")
        self.crop_image(temp_path, out_path, margin)

        # 删除临时文件
        try:
            os.remove(temp_path)
        except:
            pass

        return out_path

    def merge_rects(self, rects):
        """合并重叠的矩形（x和y方向都重叠才合并）"""
        if not rects:
            return []
        # 按 y, 然后 x 排序
        rects = sorted(rects, key=lambda r: (r.y0, r.x0))
        merged = [fitz.Rect(rects[0])]
        for r in rects[1:]:
            last = merged[-1]
            # 检查是否在 x 和 y 方向都有重叠
            if r.x0 < last.x1 and last.x0 < r.x1 and r.y0 < last.y1:
                last.x0 = min(last.x0, r.x0)
                last.x1 = max(last.x1, r.x1)
                last.y0 = min(last.y0, r.y0)
                last.y1 = max(last.y1, r.y1)
            else:
                merged.append(fitz.Rect(r))
        return merged

    def crop_image(self, image_path, output_path, margin):
        """裁剪图片到非白色内容区域"""
        with Image.open(image_path) as img:
            gray = img.convert("L")
            binary = gray.point(lambda x: 255 if x < 250 else 0)
            bbox = binary.getbbox()
            if not bbox:
                # 没有内容，保存原图
                img.save(output_path)
                return

            left, top, right, bottom = bbox
            left = max(0, left - margin)
            top = max(0, top - margin)
            right = min(img.width, right + margin)
            bottom = min(img.height, bottom + margin)
            cropped = img.crop((left, top, right, bottom))
            cropped.save(output_path)

    def update_tree_status(self, filename, status, output_path):
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            if values and values[0] == filename:
                tag = "done" if status == "完成" else "error" if status == "失败" else "pending"
                self.tree.item(item, values=(filename, status, output_path), tags=(tag,))
                break

    # ===================== 日志 =====================

    def log(self, msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)


def main():
    root = tk.Tk()
    app = PDFSanitizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
