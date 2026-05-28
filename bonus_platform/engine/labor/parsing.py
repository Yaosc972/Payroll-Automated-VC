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
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or ""))
    text = text.upper()
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
    # Remove common prefixes and suffixes
    prefixes = {"MR", "MRS", "MS", "DR", "PROF", "REV", "HON"}
    suffixes = {"JR", "SR", "II", "III", "IV", "V", "ESQ", "PHD", "MD", "DDS", "DVM"}
    particles = {"DE", "DEL", "LA", "LAS", "LOS", "VAN", "VON"}
    tokens = set()
    for token in text.split():
        if token and token not in particles and token not in prefixes and token not in suffixes:
            tokens.add(token)
    return " ".join(sorted(tokens))


def expand_name_variants(name: str) -> set:
    """Expand a name into possible variants for better matching."""
    normalized = normalize_employee_name(name)
    variants = {normalized}

    # Common nickname mappings
    nickname_map = {
        "ROBERT": {"BOB", "ROB", "BOBBY"},
        "WILLIAM": {"BILL", "WILL", "WILLY", "BILLY"},
        "JAMES": {"JIM", "JIMMY", "JAMIE"},
        "JOHN": {"JACK", "JOHNNY", "JON"},
        "MICHAEL": {"MIKE", "MIKEY"},
        "RICHARD": {"RICK", "RICH", "DICK", "RICKY"},
        "DAVID": {"DAVE", "DAVY"},
        "CHARLES": {"CHARLIE", "CHUCK"},
        "THOMAS": {"TOM", "TOMMY"},
        "DANIEL": {"DAN", "DANNY"},
        "MATTHEW": {"MATT", "MATTY"},
        "ANTHONY": {"TONY"},
        "MARK": {"MARC"},
        "STEVEN": {"STEVE", "STEVIE"},
        "PAUL": {"PAULO"},
        "ANDREW": {"ANDY", "DREW"},
        "JOSHUA": {"JOSH"},
        "KENNETH": {"KEN", "KENNY"},
        "KEVIN": {"KEV"},
        "BRIAN": {"BRYAN"},
        "GEORGE": {"GEORGIE"},
        "EDWARD": {"ED", "EDDIE", "EDDY"},
        "RONALD": {"RON", "RONNIE"},
        "TIMOTHY": {"TIM", "TIMMY"},
        "JASON": {"JAY"},
        "JEFFREY": {"JEFF", "JEFFY"},
        "RYAN": {"RY"},
        "JACOB": {"JAKE"},
        "GARY": {"GAR"},
        "NICHOLAS": {"NICK", "NICKY"},
        "ERIC": {"RICK"},
        "JONATHAN": {"JON", "JONNY"},
        "PATRICK": {"PAT", "PATTY"},
        "BENJAMIN": {"BEN", "BENNY"},
        "SAMUEL": {"SAM", "SAMMY"},
        "ALEXANDER": {"ALEX", "AL"},
        "ALEXANDRA": {"ALEX", "SANDRA"},
        "ELIZABETH": {"LIZ", "BETH", "ELIZA", "LIZZY"},
        "MARGARET": {"MAGGIE", "MEG", "PEGGY"},
        "JENNIFER": {"JEN", "JENNY"},
        "LINDA": {"LYNDA"},
        "PATRICIA": {"PAT", "PATTY", "TRISHA"},
        "JESSICA": {"JESS", "JESSIE"},
        "SARAH": {"SARA"},
        "KAREN": {"KARYN"},
        "NANCY": {"NAN"},
        "LISA": {"LEE"},
        "MARGARET": {"MAGGIE", "MEG", "PEGGY"},
        "SANDRA": {"SANDY"},
        "ASHLEY": {"ASH"},
        "DOROTHY": {"DOT", "DOTTIE"},
        "KIMBERLY": {"KIM"},
        "EMILY": {"EM", "EMMY"},
        "DONNA": {"DON"},
        "MICHELLE": {"MICKEY", "SHELLY"},
        "CAROL": {"CARRIE"},
        "AMANDA": {"MANDY"},
        "MELISSA": {"MEL", "MISSY"},
        "DEBORAH": {"DEB", "DEBBIE"},
        "STEPHANIE": {"STEPH", "STEVIE"},
        "REBECCA": {"BECKY"},
        "SHARON": {"SHERRY"},
        "CYNTHIA": {"CINDY"},
        "KATHLEEN": {"KATHY", "KAT"},
        "AMY": {"AMELIA"},
        "ANNA": {"ANN", "ANNIE"},
        "BRENDA": {"BREN"},
        "SOPHIA": {"SOPHIE"},
        "MARTHA": {"MARTIE"},
        "ALICE": {"ALLIE"},
        "JUDITH": {"JUDY"},
        "CHRISTINA": {"CHRIS", "TINA"},
        "HELEN": {"LENNA"},
        "KATHERINE": {"KATE", "KATY", "KIT"},
        "MARIE": {"MARIA"},
        "LAURA": {"LAURIE"},
        "FRANCES": {"FRAN", "FRANNIE"},
        "DIANE": {"DIANA", "DI"},
        "JANET": {"JAN"},
        "ROBIN": {"ROB"},
        "RUBY": {"RUBE"},
        "ROSE": {"ROSIE"},
        "GRACE": {"GRACIE"},
        "VIRGINIA": {"GINNY", "GINGER"},
    }

    # Expand tokens with nicknames
    expanded_tokens = []
    for token in normalized.split():
        if token in nickname_map:
            expanded_tokens.append({token} | nickname_map[token])
        else:
            expanded_tokens.append({token})

    # Generate combinations
    if len(expanded_tokens) == 1:
        variants.update(expanded_tokens[0])
    elif len(expanded_tokens) == 2:
        for first in expanded_tokens[0]:
            for last in expanded_tokens[1]:
                variants.add(f"{first} {last}")
                variants.add(f"{last} {first}")

    return variants


def display_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())
