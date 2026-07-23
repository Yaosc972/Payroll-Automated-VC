import sys
import types

from bonus_platform.engine.labor import ocr_candidate_adapter
from bonus_platform.engine.labor.ocr_candidate_adapter import (
    available_ocr_backends,
    normalize_paddleocr_result,
    normalize_rapidocr_result,
)


def test_available_ocr_backends_requires_paddle_runtime(monkeypatch):
    available_modules = {"rapidocr", "paddleocr"}
    monkeypatch.setattr(
        ocr_candidate_adapter.importlib.util,
        "find_spec",
        lambda name: object() if name in available_modules else None,
    )

    assert available_ocr_backends() == {"rapidocr": True, "paddleocr": False}


def test_normalize_rapidocr_result_preserves_text_score_and_box():
    raw = [
        (
            [[10, 20], [110, 20], [110, 40], [10, 40]],
            "Invoice Total $1,234.56",
            0.97,
        )
    ]

    page = normalize_rapidocr_result(raw, page_number=2, duration_seconds=0.4)

    assert page.backend == "rapidocr"
    assert page.page_number == 2
    assert page.text == "Invoice Total $1,234.56"
    assert page.lines[0].confidence == 0.97
    assert page.lines[0].polygon == ((10.0, 20.0), (110.0, 20.0), (110.0, 40.0), (10.0, 40.0))


def test_normalize_paddleocr_result_handles_rec_texts_and_polygons():
    raw = {
        "rec_texts": ["Employee", "Jane Doe", "$80.00"],
        "rec_scores": [0.99, 0.95, 0.93],
        "rec_polys": [
            [[5, 5], [50, 5], [50, 20], [5, 20]],
            [[5, 25], [80, 25], [80, 40], [5, 40]],
            [[90, 25], [130, 25], [130, 40], [90, 40]],
        ],
    }

    page = normalize_paddleocr_result(raw, page_number=1, duration_seconds=1.2)

    assert page.backend == "paddleocr"
    assert page.text.splitlines() == ["Employee", "Jane Doe", "$80.00"]
    assert [line.confidence for line in page.lines] == [0.99, 0.95, 0.93]
    assert page.duration_seconds == 1.2


def test_page_visual_text_groups_tokens_by_row_and_sorts_left_to_right():
    page = ocr_candidate_adapter.OcrPageResult(
        backend="rapidocr",
        page_number=1,
        lines=(
            ocr_candidate_adapter.OcrLine("$80.00", 0.98, ((300, 100), (360, 100), (360, 120), (300, 120))),
            ocr_candidate_adapter.OcrLine("Jane Doe", 0.99, ((40, 99), (130, 99), (130, 121), (40, 121))),
            ocr_candidate_adapter.OcrLine("8.00", 0.97, ((200, 101), (240, 101), (240, 119), (200, 119))),
            ocr_candidate_adapter.OcrLine("TOTAL", 0.99, ((40, 160), (100, 160), (100, 180), (40, 180))),
            ocr_candidate_adapter.OcrLine("$80.00", 0.99, ((300, 160), (360, 160), (360, 180), (300, 180))),
        ),
        duration_seconds=0.2,
    )

    assert page.visual_text == "Jane Doe 8.00 $80.00\nTOTAL $80.00"


def test_run_ocr_image_reuses_rapidocr_engine(monkeypatch, tmp_path):
    calls = {"constructed": 0, "predicted": 0}

    class FakeRapidOCR:
        def __init__(self):
            calls["constructed"] += 1

        def __call__(self, _path):
            calls["predicted"] += 1
            return []

    monkeypatch.setitem(sys.modules, "rapidocr", types.SimpleNamespace(RapidOCR=FakeRapidOCR))
    ocr_candidate_adapter.clear_ocr_engine_cache()

    ocr_candidate_adapter.run_ocr_image(tmp_path / "one.png", "rapidocr")
    ocr_candidate_adapter.run_ocr_image(tmp_path / "two.png", "rapidocr")

    assert calls == {"constructed": 1, "predicted": 2}
