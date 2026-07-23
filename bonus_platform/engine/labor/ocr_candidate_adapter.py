from __future__ import annotations

import importlib.util
import statistics
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence


Polygon = tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    polygon: Polygon


@dataclass(frozen=True)
class OcrPageResult:
    backend: str
    page_number: int
    lines: tuple[OcrLine, ...]
    duration_seconds: float
    error: str = ""

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text)

    @property
    def visual_text(self) -> str:
        positioned = [line for line in self.lines if len(line.polygon) >= 2]
        if not positioned:
            return self.text
        heights = [_line_bounds(line)[3] - _line_bounds(line)[1] for line in positioned]
        tolerance = max(4.0, statistics.median(height for height in heights if height > 0) * 0.6)
        rows: list[dict[str, Any]] = []
        for line in sorted(positioned, key=lambda item: (_line_center_y(item), _line_bounds(item)[0])):
            center_y = _line_center_y(line)
            target = next((row for row in rows if abs(float(row["center_y"]) - center_y) <= tolerance), None)
            if target is None:
                rows.append({"center_y": center_y, "lines": [line]})
                continue
            target["lines"].append(line)
            target["center_y"] = sum(_line_center_y(item) for item in target["lines"]) / len(target["lines"])
        return "\n".join(
            " ".join(line.text for line in sorted(row["lines"], key=lambda item: _line_bounds(item)[0]) if line.text)
            for row in rows
        )


def available_ocr_backends() -> dict[str, bool]:
    return {
        "rapidocr": importlib.util.find_spec("rapidocr") is not None,
        "paddleocr": (
            importlib.util.find_spec("paddleocr") is not None
            and importlib.util.find_spec("paddle") is not None
        ),
    }


def normalize_rapidocr_result(
    raw: Any,
    *,
    page_number: int,
    duration_seconds: float,
) -> OcrPageResult:
    rows = _rapidocr_rows(raw)
    lines = tuple(
        OcrLine(
            text=str(text or "").strip(),
            confidence=_score(score),
            polygon=_polygon(box),
        )
        for box, text, score in rows
        if str(text or "").strip()
    )
    return OcrPageResult("rapidocr", page_number, lines, round(duration_seconds, 4))


def normalize_paddleocr_result(
    raw: Any,
    *,
    page_number: int,
    duration_seconds: float,
) -> OcrPageResult:
    payload = _paddle_payload(raw)
    texts = _sequence(payload.get("rec_texts"))
    scores = _sequence(payload.get("rec_scores"))
    polygons = _sequence(payload.get("rec_polys") or payload.get("dt_polys"))
    lines = tuple(
        OcrLine(
            text=str(text or "").strip(),
            confidence=_score(scores[index] if index < len(scores) else 0.0),
            polygon=_polygon(polygons[index] if index < len(polygons) else ()),
        )
        for index, text in enumerate(texts)
        if str(text or "").strip()
    )
    return OcrPageResult("paddleocr", page_number, lines, round(duration_seconds, 4))


def run_ocr_image(image_path: str | Path, backend: str, *, page_number: int = 1) -> OcrPageResult:
    started = time.perf_counter()
    try:
        if backend == "rapidocr":
            raw = _ocr_engine("rapidocr")(str(image_path))
            return normalize_rapidocr_result(
                raw,
                page_number=page_number,
                duration_seconds=time.perf_counter() - started,
            )
        if backend == "paddleocr":
            engine = _ocr_engine("paddleocr")
            predictions = list(engine.predict(str(image_path)))
            raw = predictions[0] if predictions else {}
            return normalize_paddleocr_result(
                raw,
                page_number=page_number,
                duration_seconds=time.perf_counter() - started,
            )
        raise ValueError(f"unsupported OCR backend: {backend}")
    except Exception as exc:  # Candidate failures must not affect official reconciliation.
        return OcrPageResult(
            backend=backend,
            page_number=page_number,
            lines=(),
            duration_seconds=round(time.perf_counter() - started, 4),
            error=f"{type(exc).__name__}: {exc}",
        )


@lru_cache(maxsize=2)
def _ocr_engine(backend: str) -> Any:
    if backend == "rapidocr":
        from rapidocr import RapidOCR  # type: ignore

        return RapidOCR()
    if backend == "paddleocr":
        from paddleocr import PaddleOCR  # type: ignore

        return PaddleOCR(
            device="cpu",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    raise ValueError(f"unsupported OCR backend: {backend}")


def clear_ocr_engine_cache() -> None:
    _ocr_engine.cache_clear()


def _rapidocr_rows(raw: Any) -> list[tuple[Any, Any, Any]]:
    if raw is None:
        return []
    boxes = _sequence(getattr(raw, "boxes", None))
    texts = _sequence(getattr(raw, "txts", None) or getattr(raw, "texts", None))
    scores = _sequence(getattr(raw, "scores", None))
    if texts:
        return [
            (
                boxes[index] if index < len(boxes) else (),
                text,
                scores[index] if index < len(scores) else 0.0,
            )
            for index, text in enumerate(texts)
        ]
    candidate = raw[0] if isinstance(raw, tuple) and raw else raw
    if isinstance(candidate, Iterable) and not isinstance(candidate, (str, bytes, dict)):
        rows = []
        for item in candidate:
            if isinstance(item, Sequence) and len(item) >= 3:
                rows.append((item[0], item[1], item[2]))
        return rows
    return []


def _paddle_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw.get("res") if isinstance(raw.get("res"), dict) else raw
    json_value = getattr(raw, "json", None)
    if callable(json_value):
        json_value = json_value()
    if isinstance(json_value, dict):
        return json_value.get("res") if isinstance(json_value.get("res"), dict) else json_value
    result = getattr(raw, "res", None)
    return result if isinstance(result, dict) else {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value) if isinstance(value, (list, tuple)) else []


def _score(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def _polygon(value: Any) -> Polygon:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, (list, tuple)):
        return ()
    points: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            points.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    return tuple(points)


def _line_bounds(line: OcrLine) -> tuple[float, float, float, float]:
    xs = [point[0] for point in line.polygon]
    ys = [point[1] for point in line.polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _line_center_y(line: OcrLine) -> float:
    bounds = _line_bounds(line)
    return (bounds[1] + bounds[3]) / 2
