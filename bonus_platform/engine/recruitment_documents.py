"""Local approval page extraction. Text is evidence for review, never authority to apply changes."""
from __future__ import annotations

import json
import fcntl
from importlib import metadata
import logging
import re
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

DOCUMENT_VERSION = 5
DOCUMENT_REFERENCE_VERSION = 4


def _vision_available():
    return sys.platform == 'darwin' and bool(shutil.which('swift'))


def ocr_signature():
    versions = []
    for package in ('rapidocr', 'onnxruntime'):
        try: versions.append(package + ':' + metadata.version(package))
        except metadata.PackageNotFoundError: versions.append(package + ':unavailable')
    return '|'.join(['ocr-1', 'vision:' + str(_vision_available()), *versions])


def _recognize(command, images):
    output = subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    result = json.loads(output.stdout)
    expected = {str(image) for image in images}
    if (not isinstance(result, list) or len(result) != len(images)
            or any(not isinstance(item, dict) or not isinstance(item.get('image'), str)
                   or not isinstance(item.get('text', ''), str) for item in result)
            or {item.get('image') for item in result} != expected):
        raise ValueError('OCR response does not cover the requested pages')
    return {item['image']: item for item in result}


def _ocr_pages(pages, folder):
    remaining = [page for page in pages if not page.get('blank')
                 and (len(page.get('text', '').strip()) < 60 or page.get('notice'))]
    if not remaining: return
    engines = ['rapidocr']
    if _vision_available(): engines.insert(0, 'vision')
    available = False
    for engine in engines:
        images = [folder / f"page-{page['page']}.png" for page in remaining]
        if engine == 'vision':
            sdk = Path('/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk')
            command = ['swift'] + (['-sdk', str(sdk)] if sdk.exists() else []) + [str(Path(__file__).with_name('recruitment_ocr.swift'))]
        else:
            command = [sys.executable, '-m', 'bonus_platform.engine.recruitment_ocr']
        try:
            result = _recognize(command + [str(image) for image in images], images)
            available = True
        except (subprocess.SubprocessError, ValueError, OSError) as exc:
            logging.getLogger(__name__).warning('Approval OCR failed: engine=%s error=%s', engine, type(exc).__name__)
            continue
        pending = []
        for page, image in zip(remaining, images):
            found = result[str(image)]
            if found.get('text', '').strip() and not found.get('error'):
                page.update(text=found['text'], method='本地文字识别' if engine == 'vision' else '服务器文字识别',
                            ocrEngine=engine, needsVisualReview=True)
                page.pop('notice', None)
                page.pop('ocrError', None)
            else: pending.append(page)
        remaining = pending
        if not remaining: return
    for page in remaining:
        page['needsVisualReview'] = True
        page['ocrError'] = 'unrecognized' if available else 'unavailable'
        page['notice'] = ('未能识别该页文字，请补充清晰原件或人工核对' if available else
                          '扫描件文字识别暂不可用，请补充文字版或清晰原件并对照原页核对')


def mark_blank_pages(data, folder):
    """Only ignore visually empty pages, never pages whose OCR merely failed."""
    from PIL import Image
    for page in data['pages']:
        path = folder / f"page-{page['page']}.png"
        if path.is_file():
            with Image.open(path) as image:
                page['blank'] = not page.get('text', '').strip() and image.convert('L').getextrema()[0] >= 250
            if page['blank']:
                page.pop('notice', None)
                page['needsVisualReview'] = False
    return data


def unreadable_pages(data):
    return [p['page'] for p in data['pages'] if not p.get('blank')
            and (p.get('notice') or not p.get('text', '').strip())]


def mentioned_attachments(data, include_pdf=False):
    full='\n'.join(p.get('text','') for p in data['pages'])
    # Scanned OA exports frequently recognize the "l" in xlsx as I/1.
    # Normalize that extension only, never infer an attachment's basename.
    found=[(m.start(), m[1]+'.xls'+m[2].lower()) for m in re.finditer(
        r'([\w\-\u4e00-\u9fff（）()]+)\.x[lI1]s([xm]?)\b', full, re.I)]
    found.extend((m.start(), m[1]+'.'+m[2].lower()) for m in re.finditer(
        r'([\w\-\u4e00-\u9fff（）()]+)\.(png|jpe?g)\b', full, re.I))
    if include_pdf:
        # The scanned OA attachment list reads the d in .pdf as a.
        found.extend((m.start(), m[1].strip()+'.pdf') for m in re.finditer(
            r'([\w\-\u4e00-\u9fff（）()]+(?:[ \t]+[\w\-\u4e00-\u9fff（）()]+)*)\.p[da]f\b', full, re.I))
    return list(dict.fromkeys(name for _, name in sorted(found)))


def extract_document(path: Path, folder: Path):
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'extract.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try: return _extract_document(path,folder)
        finally: fcntl.flock(lock,fcntl.LOCK_UN)


def _extract_document(path: Path, folder: Path):
    cached=folder/'document.json'
    signature=ocr_signature()
    if cached.exists():
        value=json.loads(cached.read_text())
        if value.get('version') in (3, 4, DOCUMENT_VERSION) and all((folder/f"page-{p['page']}.png").is_file() for p in value['pages']):
            if value.get('version') != DOCUMENT_VERSION or value.get('ocrSignature') != signature:
                mark_blank_pages(value, folder)
                _ocr_pages(value['pages'], folder)
                value.update(version=DOCUMENT_VERSION, ocrSignature=signature)
                temp=folder/(uuid4().hex+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False));temp.replace(cached)
            return value
    folder.mkdir(parents=True,exist_ok=True)
    pages=[]
    if path.suffix.lower()=='.pdf':
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            reader=PdfReader(path)
            if reader.is_encrypted: raise ValueError('审批文件已加密，请上传可直接打开的原件')
            if not reader.pages: raise ValueError('审批文件中没有可查看的页面')
            if len(reader.pages)>80: raise ValueError('审批文件超过80页，请按流程拆分后上传')
            pages=[{'page':i+1,'text':p.extract_text() or ''} for i,p in enumerate(reader.pages)]
            subprocess.run([sys.executable,'-m',__name__,'--render',str(path),str(folder)],check=True,capture_output=True,timeout=120)
        except (PdfReadError, OSError, subprocess.SubprocessError) as exc:
            raise ValueError('无法读取审批原页，请核对文件是否完整后重试') from exc
    else:
        from PIL import Image, ImageOps, UnidentifiedImageError
        try:
            with Image.open(path) as raw:
                picture=ImageOps.exif_transpose(raw).convert('RGB');picture.thumbnail((1800,2400));picture.save(folder/'page-1.png')
        except (UnidentifiedImageError,OSError) as exc:
            raise ValueError('无法读取审批图片，请核对文件是否完整') from exc
        pages=[{'page':1,'text':''}]
    mark_blank_pages({'pages': pages}, folder)
    _ocr_pages(pages, folder)
    for page in pages:
        page.setdefault('method','原文文字' if page['text'].strip() else '人工核对')
        page.setdefault('needsVisualReview',not bool(page['text'].strip()))
    result={'version':DOCUMENT_VERSION,'pages':pages,'pageCount':len(pages),'ocrSignature':signature}
    temp=folder/(uuid4().hex+'.tmp');temp.write_text(json.dumps(result,ensure_ascii=False));temp.replace(cached)
    return result


def render_pdf(path,folder):
    # PDFium runs in its own process: its renderer is not safe for concurrent request threads.
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(str(path)) as pdf:
        for index in range(len(pdf)):
            page=pdf[index];scale=min(2.5,1800/max(page.get_size()))
            bitmap=page.render(scale=scale)
            image=bitmap.to_pil();image.save(folder/f'page-{index+1}.png')
            image.close();bitmap.close();page.close()


if __name__=='__main__' and len(sys.argv)==4 and sys.argv[1]=='--render':
    render_pdf(Path(sys.argv[2]),Path(sys.argv[3]))
