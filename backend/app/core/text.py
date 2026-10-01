"""Persian text helpers: number parsing and search-text normalisation.

The catalogue stores a normalised ``search_text`` column so product search works
with a single, predictable tokenisation for Persian (ي/ك arabic variants, ZWNJ,
Persian/Arabic digits, diacritics, tatweel).
"""

from __future__ import annotations

import re
from decimal import Decimal

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate(PERSIAN_DIGITS)}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate(ARABIC_DIGITS)})

_CHAR_MAP = {
    ord("ي"): "ی",  # ARABIC YEH -> FARSI YEH
    ord("ى"): "ی",  # ALEF MAKSURA -> FARSI YEH
    ord("ك"): "ک",  # ARABIC KAF -> KEHEH
    ord("‌"): " ",  # ZWNJ -> space
    ord("‍"): " ",  # ZWNJ (U+200D) -> space
    ord("ٔ"): "",  # ARABIC TATWEEL-ish
    ord("أ"): "ا",
    ord("إ"): "ا",
    ord("آ"): "ا",
    ord("ة"): "ه",
    ord("ؤ"): "و",
    ord("ـ"): "",
}

DIACRITICS = re.compile(r"[\u064b-\u0652\u0640]")
NON_WORD = re.compile(r"[^0-9a-z\u0600-\u06ff]+")
SPACE_RUN = re.compile(r"\s+")

MONEY_WORDS: dict[str, int] = {
    "هزار": 1_000,
    "هزار تومان": 1_000,
    "میلیون": 1_000_000,
    "میلیون تومان": 1_000_000,
    "میلیارد": 1_000_000_000,
    "تومان": 1,
    # The colloquial spelling, which drops the alef and is what most people
    # actually type: «تا ۳۰ تومن». Without it a stated budget read as no budget
    # at all, and the ceiling was silently ignored.
    "تومن": 1,
    "ریال": 10,  # 1 ریال = 10 تومان (kept explicit, Toman is canonical)
}

NUMBER_RE = re.compile(r"\d+")


def digits_to_ascii(value: str) -> str:
    return value.translate(_DIGIT_MAP)


def fold_persian(value: str) -> str:
    """Digits/character folding only — preserves case (for display values)."""
    if not value:
        return ""
    return digits_to_ascii(value).translate(_CHAR_MAP)


def normalize_persian(value: str) -> str:
    """Return a lower-cased, diacritic-free, space-separated normalised form."""
    if not value:
        return ""
    value = digits_to_ascii(value).lower()
    value = value.translate(_CHAR_MAP)
    value = DIACRITICS.sub("", value)
    return SPACE_RUN.sub(" ", value).strip()


def tokenize(value: str) -> list[str]:
    return [t for t in NON_WORD.split(normalize_persian(value)) if t]


def build_search_text(*parts: str | None) -> str:
    """Build the normalised search column value from several text parts."""
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        tokens.extend(tokenize(part))
    return " ".join(dict.fromkeys(tokens))


def numbers_in(value: str) -> list[int]:
    return [int(n) for n in NUMBER_RE.findall(digits_to_ascii(value or ""))]


FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
THOUSANDS_SEP = "\u066c"  # ٬
DECIMAL_SEP = "\u066b"  # ٫


def fa_number(value: str | int | float | Decimal) -> str:
    """Persian digits with Persian separators: 12_500_000 -> «۱۲٬۵۰۰٬۰۰۰»."""
    if isinstance(value, Decimal):
        raw = f"{value:f}".rstrip("0").rstrip(".")
    elif isinstance(value, float):
        # 12.0 reads oddly in Persian copy: show ۱۲, keep ۹٫۵
        raw = f"{value:f}".rstrip("0").rstrip(".")
    else:
        raw = str(value)
    negative = raw.startswith("-")
    if negative:
        raw = raw[1:]
    integer_part, _, fraction_part = raw.partition(".")
    grouped = f"{int(integer_part):,}" if integer_part.isdigit() else integer_part
    out = grouped.replace(",", THOUSANDS_SEP)
    if fraction_part:
        out = f"{out}{DECIMAL_SEP}{fraction_part}"
    out = out.translate(str.maketrans("0123456789", FA_DIGITS))
    return f"\u200e{out}" if negative else out


def format_toman(amount: int) -> str:
    """Human readable Toman amount in Persian digits.

    Backend explanations are user-facing copy, so they must already use Persian
    digits and the «٬» separator — the frontend only formats API numbers it
    renders itself.
    """
    return f"{fa_number(amount)} تومان"
