"""Isolated, CPU-only OCR worker for locally rendered approval pages."""
from __future__ import annotations

from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


def recognize(images):
    import onnxruntime
    import rapidocr
    from rapidocr import RapidOCR

    if 'CPUExecutionProvider' not in onnxruntime.get_available_providers():
        raise RuntimeError('Approval OCR CPU runtime is unavailable')
    model_root = Path(rapidocr.__file__).parent / 'models'
    models = {'Det.model_path': 'PP-OCRv6_det_small.onnx',
              'Cls.model_path': 'ch_ppocr_mobile_v2.0_cls_mobile.onnx',
              'Rec.model_path': 'PP-OCRv6_rec_small.onnx'}
    if not all((model_root / name).is_file() for name in models.values()):
        raise FileNotFoundError('Bundled approval OCR models are incomplete')
    engine = RapidOCR(params={
        'Global.log_level': 'error',
        'EngineConfig.onnxruntime.intra_op_num_threads': 2,
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        **{key: str(model_root / name) for key, name in models.items()},
    })
    results = []
    for image in images:
        item = {'image': str(image)}
        try:
            result = engine(str(Path(image).resolve(strict=True)))
            lines = result.txts if result.txts is not None else []
            item['text'] = '\n'.join(str(line) for line in lines if str(line).strip())
        except Exception:
            item['error'] = 'PAGE_OCR_FAILED'
        results.append(item)
    return results


def check():
    from PIL import Image, ImageDraw

    with TemporaryDirectory(prefix='recruitment-ocr-check-') as temporary:
        image = Image.new('RGB', (240, 60), 'white')
        ImageDraw.Draw(image).text((15, 15), 'OCR TEST 12345', fill='black')
        path = Path(temporary)/'check.png'
        image.resize((960, 240)).save(path)
        result = recognize([str(path)])[0]
        if '12345' not in result.get('text', '').replace(' ', ''):
            raise RuntimeError('Approval OCR self-check failed')
    return {'ok': True, 'engine': 'rapidocr', 'models': 'bundled', 'device': 'CPU'}


if __name__ == '__main__':
    with redirect_stdout(sys.stderr):
        result = check() if sys.argv[1:] == ['--check'] else recognize(sys.argv[1:])
    json.dump(result, sys.stdout, ensure_ascii=False)
