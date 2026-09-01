#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
挪威工资 PDF · 自建模板解析脚手架
=================================
适用场景：文本层 PDF（挪威薪资单绝大多数为数字化生成，含文本层，无需 OCR）
方法核心：基于「锚点 anchor + 坐标」的模板提取，按供应商建模板库
依赖：pip install pdfplumber pyyaml

为什么不用「整页正则」而用「锚点+坐标」？
  - 挪威 PDF 标签是挪威语（Bruttolønn / Netto utbetaling / Skattekort...），
    同一字段在不同供应商版式里位置不同、甚至分页；但「标签→紧邻的值」关系稳定。
  - 用坐标找锚点标签，再取它右侧/下方的词，比全文正则更稳、更不易串字段。

挪威数字格式坑（已在本脚本处理）：
  - 逗号是小数位：12,50  -> 12.50
  - 空格是千位位：1 234 567 -> 1234567
  - 用的是 NBSP(U+00A0) 或 窄NBSP(U+202F)，不是普通空格！必须一并清洗
  - 可能带 "kr" / "NOK" 后缀
"""

import re
import json
import csv
import os
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None
try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# ----------------------------------------------------------------------
# 1) 挪威数字格式归一化
# ----------------------------------------------------------------------
def normalize_no_number(raw):
    """把挪威格式的数字字符串转成 float。无法解析返回 None。"""
    if raw is None:
        return None
    s = str(raw)
    # 清洗 NBSP / 窄NBSP / 普通空格（先统一成普通空格再去掉）
    s = s.replace('\u00a0', ' ').replace('\u202f', ' ').replace('\u2009', ' ')
    s = s.replace('kr', '').replace('NOK', '').strip()
    # 挪威：逗号=小数，空格=千位
    s = s.replace(' ', '')            # 去千位空格
    if ',' in s and '.' in s:
        # 既有逗号又有点：点当千位、逗号当小数（防御性，挪威 PDF 通常不出此格式）
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    m = re.search(r'-?\d+(?:\.\d+)?', s)
    return float(m.group()) if m else None


# ----------------------------------------------------------------------
# 2) 取词 + 锚点定位
# ----------------------------------------------------------------------
def get_words(page):
    """返回页面全部词及其坐标。"""
    out = []
    for w in page.extract_words(use_text_flow=False, keep_blank_chars=False):
        out.append({'text': w['text'], 'x0': w['x0'], 'top': w['top']})
    return out


def get_lines(words, y_tol=6):
    """把词按行分组（同一视觉行 top 接近）。"""
    if not words:
        return []
    sw = sorted(words, key=lambda w: (w['top'], w['x0']))
    lines, cur = [], [sw[0]]
    for w in sw[1:]:
        if abs(w['top'] - cur[0]['top']) <= y_tol:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
    lines.append(cur)
    return lines


def find_anchor(words, anchor_re):
    """
    找锚点：支持「单 token」与「多词短语」两种匹配。
      1) 先整词精确匹配（避免 "Skattetrekk" 误命中 "Feriepenger u/skattetrekk"）
      2) 再逐词子串匹配（向后兼容，用于含正则/部分匹配的锚点）
      3) 最后按整行文本匹配（应对 Totalt i 2026 / Fast bilgodtgjørelse
         这类被拆成多个词、但同处一行的短语锚点）
    返回带坐标的锚点 dict（短语命中时取该行首个词的坐标）。
    """
    pat = re.compile(anchor_re, re.IGNORECASE)
    # 阶段1：整词精确匹配
    for w in words:
        if pat.fullmatch(w['text']):
            return w
    # 阶段2：子串匹配
    for w in words:
        if pat.search(w['text']):
            return w
    # 阶段3：整行匹配（多词短语）
    for line in get_lines(words):
        line.sort(key=lambda w: w['x0'])
        txt = ' '.join(w['text'] for w in line)
        if pat.search(txt):
            return {'text': line[0]['text'],
                    'x0': line[0]['x0'],
                    'top': line[0]['top']}
    return None


def capture_value(words, anchor, rule):
    """
    根据规则从锚点取数：
      mode=right              -> 取同一行、锚点右侧、最靠近的词（合并同行后续词，应对 "45 000,00"）
      mode=rightmost_numeric  -> 取同一行、最右侧的可解析数字（适用于表格右列 Beløp）
      mode=below              -> 取锚点正下方、x 接近的词
      mode=regex              -> 取同一行文本，再用正则捕获目标
      mode=top_left           -> 取页面/分段的左上角第一行（适合员工姓名）
      mode=region             -> 取指定矩形区域内的所有文字
    """
    mode = rule.get('mode', 'right')

    if mode == 'top_left':
        if not words:
            return None
        y_tol = rule.get('y_tol', 6)
        min_top = min(w['top'] for w in words)
        top_line = [w for w in words if abs(w['top'] - min_top) <= y_tol]
        top_line.sort(key=lambda w: w['x0'])
        return ' '.join(w['text'] for w in top_line).strip()

    if mode == 'region':
        x_min = rule.get('x_min', 0)
        x_max = rule.get('x_max', 9999)
        y_min = rule.get('y_min', 0)
        y_max = rule.get('y_max', 9999)
        region = [w for w in words
                  if x_min <= w['x0'] <= x_max and y_min <= w['top'] <= y_max]
        region.sort(key=lambda w: (w['top'], w['x0']))
        return ' '.join(w['text'] for w in region).strip()

    if mode == 'rightmost_numeric':
        # 关键：挪威数字「千位数用空格/NBSP 分隔」，PDF 会把它拆成多个 token
        # （如 "60 356,00" -> "60" + "356,00"）。不能只取最右侧单 token，
        # 否则会丢掉高位。做法：取整行文本，正则抓「最右侧的完整挪威数字」。
        # 另外挪威扣税常为负数（如 -8 318,00），需保留负号；PDF 里负号可能与数字
        # 分开（"- 8 318,00"），先紧凑化再匹配。
        y_tol = rule.get('y_tol', 6)
        line = [w for w in words if abs(w['top'] - anchor['top']) <= y_tol]
        line.sort(key=lambda w: w['x0'])
        full = ' '.join(w['text'] for w in line)
        full = re.sub(r'-\s+', '-', full)  # 把 "- 8 318,00" 变成 "-8 318,00"
        cand = None
        for mm in re.finditer(r'-?\d{1,3}(?:[ \u00a0\u202f]\d{3})*(?:,\d+)?', full):
            cand = mm.group(0)
        return cand

    if mode == 'regex':
        y_tol = rule.get('y_tol', 6)
        line = [w for w in words if abs(w['top'] - anchor['top']) <= y_tol]
        line.sort(key=lambda w: w['x0'])
        txt = ' '.join(w['text'] for w in line)
        pattern = rule.get('pattern')
        if not pattern:
            return None
        m = re.search(pattern, txt)
        if not m:
            return None
        return m.group(1) if m.groups() else m.group(0)

    if mode == 'right':
        y_tol = rule.get('y_tol', 6)
        line = [w for w in words
                if abs(w['top'] - anchor['top']) <= y_tol and w['x0'] >= anchor['x0'] - 1]
        line.sort(key=lambda w: w['x0'])
        right = [w['text'] for w in line if w['x0'] > anchor['x0']]
        return ' '.join(right).strip() if right else None

    if mode == 'below':
        x_tol = rule.get('x_tol', 40)
        below = [w for w in words
                 if w['top'] > anchor['top'] and abs(w['x0'] - anchor['x0']) <= x_tol]
        if not below:
            return None
        below.sort(key=lambda w: w['top'])
        return below[0]['text']

    return None


# ----------------------------------------------------------------------
# 3) 解析单个 PDF
# ----------------------------------------------------------------------
def parse_pdf(pdf_path, template):
    if pdfplumber is None:
        raise RuntimeError("请先安装 pdfplumber: pip install pdfplumber")
    results, exceptions = {}, []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:                      # 支持多页/多员工
            words = get_words(page)
            # 按 top -> x0 排序，确保 "第一个锚点" 就是页面最上方的那个
            words.sort(key=lambda w: (w['top'], w['x0']))

            for fname, fcfg in template.get('fields', {}).items():
                mode = fcfg.get('capture', {}).get('mode', 'right')
                scope = words

                # 支持按章节/分段限定搜索范围（例如：本页 YTD 区 vs 本月明细区）
                sec = fcfg.get('section')
                if sec:
                    sec_anchor = find_anchor(words, sec['anchor'])
                    if not sec_anchor:
                        exceptions.append(f"[{fname}] 未找到分段锚点: {sec['anchor']}")
                        continue
                    y = sec_anchor['top']
                    offset = sec.get('offset', 5)
                    rel = sec.get('relation', 'below')
                    if rel == 'below':
                        scope = [w for w in words if w['top'] > y + offset]
                    elif rel == 'above':
                        scope = [w for w in words if w['top'] < y - offset]

                # 部分 mode 可不依赖 anchor（top_left / region）
                anchor = None
                need_anchor = mode not in ('top_left', 'region')
                if 'anchor' in fcfg:
                    anchor = find_anchor(scope, fcfg['anchor'])
                    if not anchor and need_anchor:
                        exceptions.append(f"[{fname}] 未找到锚点: {fcfg['anchor']}")
                        continue
                elif need_anchor:
                    exceptions.append(f"[{fname}] 配置缺少 anchor")
                    continue

                raw = capture_value(scope, anchor, fcfg.get('capture', {}))
                if raw is None:
                    exceptions.append(f"[{fname}] 锚点已找到但取值为空")
                    continue
                if fcfg.get('type') == 'number':
                    val = normalize_no_number(raw)
                    if val is None:
                        exceptions.append(f"[{fname}] 取值[{raw}]无法转数字")
                else:
                    val = raw
                results[fname] = val
    return results, exceptions


# ----------------------------------------------------------------------
# 4) 校验层（勾稽 + 税款数学 + 实发校验 + 必填 + 环比）
# ----------------------------------------------------------------------
def validate(results, template, prev=None):
    alerts = []
    for f in template.get('required', []):
        if f not in results or results[f] is None:
            alerts.append(f"必填字段缺失: {f}")
    for sc in template.get('sum_checks', []):
        total = results.get(sc['total'])
        parts = [results.get(p) for p in sc['parts']]
        if total is not None and all(p is not None for p in parts):
            s = sum(parts)
            if abs(s - total) > sc.get('tol', 1.0):
                alerts.append(f"勾稽失败: {sc['total']}={total} ≠ Σ{sc['parts']}={round(s,2)}")

    # 税款数学校验：税前基数 × 税率 ≈ |代扣税|（允许四舍五入误差）
    for tmc in template.get('tax_math_checks', []):
        base = results.get(tmc['base'])
        pct = results.get(tmc['percent'])
        tax = results.get(tmc['tax'])
        if base is not None and pct is not None and tax is not None:
            expected = base * pct / 100.0
            actual = abs(tax)
            if abs(expected - actual) > tmc.get('tol', 2.0):
                alerts.append(f"税额校验失败: {tmc['base']}×{tmc['percent']}%≈{round(expected,2)}, 实际扣税={tax}")

    # 实发校验：实发 ≈ Σ(本月存在收入项) + 代扣税
    # 收入项组合每月可能不同（Fastlønn / Feriepenger / Bonus ...），只核对实际取到的项
    for pc in template.get('payout_checks', []):
        payout = results.get(pc['payout'])
        tax = results.get(pc['tax'])
        income = [results.get(f) for f in pc.get('income_fields', [])]
        present_income = [v for v in income if v is not None]
        if payout is not None and tax is not None and present_income:
            # 实发 = Σ(本月收入项) − 代扣税（代扣税以正数存储，需减）
            s = sum(present_income) - abs(tax)
            if abs(s - payout) > pc.get('tol', 1.0):
                missing_note = "" if len(present_income) == len(income) else f"（收入项部分缺失，仅核对 {len(present_income)}/{len(income)} 项）"
                alerts.append(f"实发校验失败: {pc['payout']}={payout} ≠ Σ收入+税={round(s,2)}{missing_note}")

    if prev:
        thr = template.get('delta_alert', 0.3)
        for f, v in results.items():
            if isinstance(v, (int, float)) and f in prev and isinstance(prev[f], (int, float)):
                base = abs(prev[f]) or 1
                if abs(v - prev[f]) / base > thr:
                    alerts.append(f"环比波动>{int(thr*100)}%: {f} {prev[f]}→{v}")
    return alerts


# ----------------------------------------------------------------------
# 5) 批量运行 + 输出
# ----------------------------------------------------------------------
def run_folder(pdf_dir, template_path, out_csv, prev_json=None):
    if yaml is None:
        raise RuntimeError("请先安装 pyyaml: pip install pyyaml")
    template = yaml.safe_load(Path(template_path).read_text(encoding='utf-8'))
    prev = json.loads(Path(prev_json).read_text(encoding='utf-8')) if prev_json and Path(prev_json).exists() else None

    rows, all_exceptions = [], []
    for pdf_path in sorted(Path(pdf_dir).glob('*.pdf')):
        res, exc = parse_pdf(str(pdf_path), template)
        alerts = validate(res, template, prev)
        res['_file'] = pdf_path.name
        res['_exceptions'] = '; '.join(exc)
        res['_alerts'] = '; '.join(alerts)
        rows.append(res)
        all_exceptions += [f"{pdf_path.name}: {e}" for e in exc + alerts]

    fields = ['_file'] + list(template.get('fields', {}).keys()) + ['_exceptions', '_alerts']
    with open(out_csv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in fields})

    print(f"已处理 {len(rows)} 个 PDF -> {out_csv}")
    if all_exceptions:
        print(f"\n⚠ 需人工复核 {len(all_exceptions)} 项：")
        for e in all_exceptions:
            print("  -", e)
    return rows


# ----------------------------------------------------------------------
# 6) 命令行入口
# ----------------------------------------------------------------------
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print("用法:")
        print("  单文件调试 : python norway_pdf_parser.py one <pdf> <template.yaml>")
        print("  批量跑     : python norway_pdf_parser.py batch <pdf_dir> <template.yaml> <out.csv> [prev.json]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'one':
        tpl = yaml.safe_load(Path(sys.argv[3]).read_text(encoding='utf-8'))
        res, exc = parse_pdf(sys.argv[2], tpl)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if exc:
            print("异常:", exc)
    elif cmd == 'batch':
        run_folder(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
