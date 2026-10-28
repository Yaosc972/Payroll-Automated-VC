import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from bonus_platform.engine import recruitment_documents as documents


def picture(path, blank=False):
    image = Image.new('RGB', (400, 120), 'white')
    if not blank: ImageDraw.Draw(image).text((15, 20), 'Approval 12345', fill='black')
    image.save(path)


def response(images, text='候选甲申请剔除10天招聘周期。'):
    return {str(image): {'image': str(image), 'text': text} for image in images}


def test_non_macos_uses_server_ocr_and_retains_visual_review(tmp_path, monkeypatch):
    source = tmp_path/'scan.png'; picture(source)
    calls = []
    monkeypatch.setattr(documents, '_vision_available', lambda: False)
    def recognize(command, images):
        calls.append(command)
        return response(images)
    monkeypatch.setattr(documents, '_recognize', recognize)
    result = documents.extract_document(source, tmp_path/'document')
    assert calls[0][1:3] == ['-m', 'bonus_platform.engine.recruitment_ocr']
    page = result['pages'][0]
    assert page['text'] == '候选甲申请剔除10天招聘周期。'
    assert page['ocrEngine'] == 'rapidocr' and page['needsVisualReview']
    assert not documents.unreadable_pages(result)


def test_vision_partial_failure_only_sends_unread_pages_to_fallback(tmp_path, monkeypatch):
    for n in (1, 2): picture(tmp_path/f'page-{n}.png')
    monkeypatch.setattr(documents, '_vision_available', lambda: True)
    calls = []
    def recognize(command, images):
        calls.append([Path(image).name for image in images])
        if len(calls) == 1:
            return {str(images[0]): {'text': '第一份审批'}, str(images[1]): {'error': 'FAILED'}}
        return response(images, '第二份审批')
    monkeypatch.setattr(documents, '_recognize', recognize)
    pages = [{'page': 1, 'text': ''}, {'page': 2, 'text': ''}]
    documents._ocr_pages(pages, tmp_path)
    assert calls == [['page-1.png', 'page-2.png'], ['page-2.png']]
    assert [p['ocrEngine'] for p in pages] == ['vision', 'rapidocr']


def test_failed_legacy_scan_is_recovered_without_source_or_rerender(tmp_path, monkeypatch):
    picture(tmp_path/'page-1.png')
    (tmp_path/'document.json').write_text(json.dumps({'version': 4, 'pageCount': 1,
        'pages': [{'page': 1, 'text': '', 'notice': 'OCR不可用'}]}))
    monkeypatch.setattr(documents, '_vision_available', lambda: False)
    calls = []
    def recognize(command, images):
        calls.append(command)
        return response(images)
    monkeypatch.setattr(documents, '_recognize', recognize)
    result = documents.extract_document(tmp_path/'source-no-longer-needed.pdf', tmp_path)
    assert result['version'] == documents.DOCUMENT_VERSION
    assert not documents.unreadable_pages(result)
    assert documents.extract_document(tmp_path/'source-no-longer-needed.pdf', tmp_path) == result
    assert len(calls) == 1


def test_installing_ocr_retries_failed_cache_once_and_preserves_partial_text(tmp_path, monkeypatch):
    picture(tmp_path/'page-1.png')
    (tmp_path/'document.json').write_text(json.dumps({'version': 4, 'pageCount': 1,
        'pages': [{'page': 1, 'text': '原件已读取的一部分文字'}]}))
    monkeypatch.setattr(documents, '_vision_available', lambda: False)
    signature = ['unavailable']
    monkeypatch.setattr(documents, 'ocr_signature', lambda: signature[0])
    calls = []
    def recognize(command, images):
        calls.append(command)
        if signature[0] == 'unavailable': raise subprocess.TimeoutExpired(command, 180)
        return response(images)
    monkeypatch.setattr(documents, '_recognize', recognize)
    failed = documents.extract_document(tmp_path/'not-needed.pdf', tmp_path)
    assert failed['pages'][0]['text'] == '原件已读取的一部分文字'
    assert failed['pages'][0]['ocrError'] == 'unavailable'
    assert documents.unreadable_pages(failed) == [1]
    assert documents.extract_document(tmp_path/'not-needed.pdf', tmp_path) == failed
    assert len(calls) == 1
    signature[0] = 'installed'
    recovered = documents.extract_document(tmp_path/'not-needed.pdf', tmp_path)
    assert not documents.unreadable_pages(recovered) and len(calls) == 2


def test_empty_ocr_is_not_treated_as_a_blank_page(tmp_path, monkeypatch):
    source = tmp_path/'scan.png'; picture(source)
    monkeypatch.setattr(documents, '_vision_available', lambda: False)
    monkeypatch.setattr(documents, '_recognize', lambda command, images: response(images, ''))
    result = documents.extract_document(source, tmp_path/'document')
    assert not result['pages'][0]['blank']
    assert documents.unreadable_pages(result) == [1]
    assert '未能识别' in result['pages'][0]['notice']


@pytest.mark.parametrize('result', [[], [{'image': 'wrong.png', 'text': '文字'}],
                                  [{'image': ['page.png'], 'text': '文字'}]])
def test_partial_or_wrong_page_response_is_rejected(tmp_path, monkeypatch, result):
    monkeypatch.setattr(documents.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(result)))
    with pytest.raises(ValueError): documents._recognize(['ocr'], [tmp_path/'page.png'])


def test_text_pdf_does_not_depend_on_an_ocr_runtime(tmp_path, monkeypatch):
    source = tmp_path/'native.pdf'
    writer = PdfWriter(); page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 40 700 Td (Approval original text. Employee zt12345. Approved recruitment cycle exclusion of ten days.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    with source.open('wb') as out: writer.write(out)
    def unexpected(*args): raise AssertionError('Native text PDF must not require OCR')
    monkeypatch.setattr(documents, '_recognize', unexpected)
    result = documents.extract_document(source, tmp_path/'document')
    assert 'zt12345' in result['pages'][0]['text']
    assert result['pages'][0]['method'] == '原文文字'
    assert not documents.unreadable_pages(result)
