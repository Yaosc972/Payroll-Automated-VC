from __future__ import annotations

import re
import unicodedata
from typing import Any


def parse_number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in {"-", "$", "-$", "$-", "—"}:
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in {"", "-", "."}:
        return 0.0
    try:
        number = float(cleaned)
    except ValueError:
        return 0.0
    return -number if negative else number


def normalize_employee_name(value: Any) -> str:
    text = str(value or "").upper()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"#\d+\s*", " ", text)
    text = re.sub(r"\b\d{3,6}\b", " ", text)
    text = re.sub(r"[^A-Z,\-\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    if "," in text:
        last, first = [part.strip() for part in text.split(",", 1)]
        text = f"{first} {last}"
    text = text.replace("-", " ")
    particles = {"DE", "DEL", "LA", "LAS", "LOS", "VAN", "VON"}
    tokens = [token for token in text.split() if token and token not in particles]
    return " ".join(sorted(tokens))


def display_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())

