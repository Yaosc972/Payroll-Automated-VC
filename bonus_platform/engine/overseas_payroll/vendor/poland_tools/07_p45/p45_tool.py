#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P45 PDF Processor Tool
======================
Extracts Surname, First name, Leaving date, and National Insurance number
from UK P45 PDF forms, then renames and password-protects the PDF.

Filename format: {Surname} {First name(s)} - {DD.MM.YYYY} - P45.pdf
Password: Employee's National Insurance number (9 characters)

Usage:
  GUI mode:   python p45_tool.py
  CLI mode:   python p45_tool.py <file1.pdf> [file2.pdf ...]
              python p45_tool.py --dir <directory>
"""

import fitz          # PyMuPDF
import re
import os
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# National Insurance number: 2 uppercase letters + 6 digits + 1 uppercase letter
NI_PATTERN = re.compile(r'\b([A-Z]{2}\d{6}[A-Z])\b')

# Title values that appear on P45 forms
TITLE_VALUES = {'MR', 'MRS', 'MISS', 'MS', 'DR', 'PROF', 'REV', 'CAPT', 'SIR',
                'LORD', 'LADY', 'MX', 'MSTR'}
TITLE_PATTERN = re.compile(r'^(MR|MRS|MISS|MS|DR|PROF|REV|CAPT|SIR|LORD|LADY|MX|MSTR)$')

# Characters not allowed in Windows filenames
INVALID_FILENAME_CHARS = '<>:"/\\|?*'


# ---------------------------------------------------------------------------
# Core extraction logic
# ---------------------------------------------------------------------------

def extract_p45_info(pdf_path):
    """
    Extract P45 fields from a PDF file.

    Returns a dict with keys: surname, first_name, leaving_date, ni_number.
    Any field that cannot be found will be None.
    """
    doc = fitz.open(pdf_path)
    page = doc[0]  # First page has all the data we need
    raw_text = page.get_text()
    doc.close()

    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]

    # ---- 1. National Insurance number ----------------------------------------
    ni_number = None
    ni_index = None
    for i, line in enumerate(lines):
        m = NI_PATTERN.search(line)
        if m:
            ni_number = m.group(1)
            ni_index = i
            break

    # ---- 2. Title (MR / MRS / MS / ...) --------------------------------------
    title_index = None
    for i, line in enumerate(lines):
        if TITLE_PATTERN.match(line):
            title_index = i
            break

    # ---- 3. Surname (line immediately before the title) -----------------------
    surname = None
    if title_index is not None and title_index > 0:
        candidate = lines[title_index - 1]
        # Make sure it's not a number or the title itself
        if not candidate.isdigit() and candidate.upper() not in TITLE_VALUES:
            surname = candidate

    # ---- 4. First name(s) (line immediately after the NI number) -------------
    first_name = None
    if ni_index is not None and ni_index + 1 < len(lines):
        candidate = lines[ni_index + 1]
        # Make sure it's not a number or the NI number itself
        if not candidate.isdigit() and not NI_PATTERN.match(candidate):
            first_name = candidate

    # ---- 5. Leaving date DD MM YYYY (three consecutive values after title) ---
    leaving_date = None
    if title_index is not None:
        for i in range(title_index + 1, len(lines) - 2):
            dd, mm, yyyy = lines[i], lines[i + 1], lines[i + 2]
            if (dd.isdigit() and 1 <= int(dd) <= 31
                    and mm.isdigit() and 1 <= int(mm) <= 12
                    and yyyy.isdigit() and len(yyyy) == 4
                    and 2000 <= int(yyyy) <= 2100):
                leaving_date = f"{int(dd):02d}.{int(mm):02d}.{yyyy}"
                break

    return {
        'surname': surname,
        'first_name': first_name,
        'leaving_date': leaving_date,
        'ni_number': ni_number,
    }


def _sanitize_filename(name):
    """Remove characters that are invalid in Windows filenames."""
    for ch in INVALID_FILENAME_CHARS:
        name = name.replace(ch, '')
    return name.strip()


def process_pdf(pdf_path, keep_original=True, log=print):
    """
    Process a single P45 PDF:
      1. Extract fields
      2. Build new filename:  {Surname} {First name} - {DD.MM.YYYY} - P45.pdf
      3. Save an encrypted copy (password = NI number) with the new name

    Parameters
    ----------
    pdf_path : str
        Path to the source PDF.
    keep_original : bool
        If True (default) the original file is left untouched.
    log : callable
        Function that receives progress messages (default: print).

    Returns
    -------
    (bool, str)  – (success, message)
    """
    short_name = os.path.basename(pdf_path)
    log(f"\n{'─'*60}")
    log(f"Processing: {short_name}")

    # -- Extract -------------------------------------------------------------
    try:
        info = extract_p45_info(pdf_path)
    except Exception as exc:
        msg = f"  [ERROR] Cannot read PDF: {exc}"
        log(msg)
        return False, msg

    # -- Validate ------------------------------------------------------------
    missing = [k for k, v in info.items() if not v]
    if missing:
        msg = f"  [ERROR] Missing fields: {', '.join(missing)}"
        log(msg)
        return False, msg

    log(f"  Surname     : {info['surname']}")
    log(f"  First name  : {info['first_name']}")
    log(f"  Leaving date: {info['leaving_date']}")
    log(f"  NI number   : {info['ni_number']}  (password)")

    # -- Build output path ---------------------------------------------------
    new_basename = _sanitize_filename(
        f"{info['surname']} {info['first_name']} - {info['leaving_date']} - P45"
    ) + ".pdf"
    out_dir = os.path.dirname(pdf_path) or '.'
    out_path = os.path.join(out_dir, new_basename)

    if os.path.abspath(out_path) == os.path.abspath(pdf_path):
        msg = "  [SKIP] Output path is same as input — nothing to do."
        log(msg)
        return False, msg

    if os.path.exists(out_path):
        msg = f"  [SKIP] Output already exists: {new_basename}"
        log(msg)
        return False, msg

    # -- Encrypt & save ------------------------------------------------------
    try:
        doc = fitz.open(pdf_path)
        # AES-256 encryption, password required to open
        doc.save(
            out_path,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=info['ni_number'],
            owner_pw=info['ni_number'],
            garbage=4,          # clean up unused objects
            deflate=True,       # compress streams
        )
        doc.close()
    except Exception as exc:
        msg = f"  [ERROR] Failed to encrypt/save: {exc}"
        log(msg)
        return False, msg

    # -- Optionally remove original ------------------------------------------
    if not keep_original:
        try:
            os.remove(pdf_path)
        except OSError:
            pass  # non-fatal

    msg = f"  [OK] Created: {new_basename}"
    log(msg)
    return True, msg


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------

def process_directory(dir_path, log=print):
    """Process every .pdf file inside *dir_path* (non-recursive)."""
    pdfs = sorted(
        os.path.join(dir_path, f)
        for f in os.listdir(dir_path)
        if f.lower().endswith('.pdf')
    )
    if not pdfs:
        log("No PDF files found in the selected directory.")
        return

    log(f"Found {len(pdfs)} PDF file(s) in {dir_path}")
    ok = fail = 0
    for pdf in pdfs:
        success, _ = process_pdf(pdf, log=log)
        if success:
            ok += 1
        else:
            fail += 1

    log(f"\n{'═'*60}")
    log(f"Batch complete — {ok} succeeded, {fail} failed, {len(pdfs)} total")


# ===========================================================================
#  GUI  (tkinter)
# ===========================================================================

def run_gui():
    """Launch the tkinter GUI."""
    import tkinter as tk
    from tkinter import filedialog, ttk, scrolledtext
    import threading

    BG       = '#f5f5f5'
    ACCENT   = '#2563eb'
    OK_COLOR = '#16a34a'
    ERR_COLOR = '#dc2626'
    FONT     = ('Microsoft YaHei UI', 10)
    FONT_MONO = ('Consolas', 10)

    root = tk.Tk()
    root.title("P45 PDF 处理工具")
    root.geometry('780x560')
    root.configure(bg=BG)

    style = ttk.Style()
    style.theme_use('clam')
    style.configure('TFrame', background=BG)
    style.configure('TLabel', background=BG, font=FONT)
    style.configure('TButton', font=FONT, padding=6)
    style.configure('Accent.TButton', foreground='white', background=ACCENT)
    style.map('Accent.TButton',
              background=[('active', '#1d4ed8'), ('disabled', '#9ca3af')])
    style.configure('Horizontal.TProgressbar', thickness=8)

    # ---- layout ------------------------------------------------------------
    outer = ttk.Frame(root, padding=12)
    outer.pack(fill='both', expand=True)

    # button row
    top = ttk.Frame(outer)
    top.pack(fill='x', pady=(0, 8))

    state = {'files': [], 'running': False}

    def set_running(val):
        state['running'] = val
        for w in (btn_file, btn_dir, btn_process):
            w.config(state='normal' if not val else 'disabled')

    def pick_files():
        files = filedialog.askopenfilenames(
            title='选择 P45 PDF 文件',
            filetypes=[('PDF 文件', '*.pdf'), ('所有文件', '*.*')],
        )
        if files:
            state['files'] = list(files)
            lbl_count.config(text=f'已选择 {len(files)} 个文件')
            btn_process.config(state='normal' if not state['running'] else 'disabled')

    def pick_dir():
        d = filedialog.askdirectory(title='选择包含 P45 PDF 的文件夹')
        if not d:
            return
        pdfs = sorted(
            os.path.join(d, f) for f in os.listdir(d)
            if f.lower().endswith('.pdf')
        )
        state['files'] = pdfs
        lbl_count.config(text=f'在文件夹中找到 {len(pdfs)} 个 PDF 文件')
        btn_process.config(state='normal' if pdfs and not state['running'] else 'disabled')

    def append_log(text, tag=None):
        txt_log.configure(state='normal')
        if tag:
            txt_log.insert('end', text + '\n', tag)
        else:
            txt_log.insert('end', text + '\n')
        txt_log.see('end')
        txt_log.configure(state='disabled')
        root.update_idletasks()

    def worker():
        set_running(True)
        prog['maximum'] = len(state['files'])
        prog['value'] = 0
        ok = fail = 0
        for i, f in enumerate(state['files']):
            success, _ = process_pdf(f, log=lambda m: append_log(m))
            if success:
                ok += 1
            else:
                fail += 1
            prog['value'] = i + 1
        append_log('')
        append_log(f'══ 完成 — 成功 {ok}，失败 {fail}，共 {len(state["files"])} ══',
                   'ok' if fail == 0 else 'err')
        set_running(False)

    def start():
        if not state['files'] or state['running']:
            return
        txt_log.configure(state='normal')
        txt_log.delete('1.0', 'end')
        txt_log.configure(state='disabled')
        threading.Thread(target=worker, daemon=True).start()

    btn_file    = ttk.Button(top, text='选择文件', command=pick_files)
    btn_dir     = ttk.Button(top, text='选择文件夹', command=pick_dir)
    btn_process = ttk.Button(top, text='开始处理', style='Accent.TButton',
                             command=start, state='disabled')

    btn_file.pack(side='left', padx=(0, 6))
    btn_dir.pack(side='left', padx=(0, 6))
    btn_process.pack(side='left')

    lbl_count = ttk.Label(outer, text='未选择文件')
    lbl_count.pack(anchor='w', pady=(0, 6))

    prog = ttk.Progressbar(outer, mode='determinate')
    prog.pack(fill='x', pady=(0, 8))

    txt_log = scrolledtext.ScrolledText(outer, height=18, wrap='word',
                                        font=FONT_MONO, bg='white',
                                        borderwidth=1, relief='solid')
    txt_log.tag_config('ok',  foreground=OK_COLOR)
    txt_log.tag_config('err', foreground=ERR_COLOR)
    txt_log.pack(fill='both', expand=True)

    root.mainloop()


# ===========================================================================
#  Entry point
# ===========================================================================

def main():
    args = sys.argv[1:]

    if not args:
        run_gui()
        return

    # CLI mode
    if args[0] in ('-h', '--help'):
        print(__doc__)
        return

    if args[0] == '--dir' and len(args) > 1:
        process_directory(args[1])
        return

    # Treat every argument as a file path
    for path in args:
        if os.path.isfile(path):
            process_pdf(path)
        elif os.path.isdir(path):
            process_directory(path)
        else:
            print(f"[SKIP] Not found: {path}")


if __name__ == '__main__':
    main()
