"""Chuẩn hoá / phân tích số tiền kiểu Việt Nam.

Hỗ trợ: 1.480.000 | 1,480,000 | 1480000 | 159k | 1tr2 | 2 triệu | 1,5tr | 500 nghìn
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

__all__ = ["parse_money", "format_money", "extract_money_tokens"]

_UNITS: dict[str, int] = {
    "k": 1_000,
    "ng": 1_000,
    "nghin": 1_000,
    "ngan": 1_000,
    "tr": 1_000_000,
    "trieu": 1_000_000,
    "m": 1_000_000,
    "ty": 1_000_000_000,
    "b": 1_000_000_000,
}

_UNIT_ALT = r"k|ng|nghìn|ngàn|tr|triệu|tỷ|ty|trieu|m|b"

# "1tr2" / "2tr5" / "3m7" -> 1.200.000 ; rất phổ biến khi chat
_SHORTHAND = re.compile(
    rf"(?<![\w.,])(\d{{1,3}})\s*({_UNIT_ALT})\s*(\d)(?![\d])", re.IGNORECASE
)

# Một số tiền thường: không dính chữ phía trước (tránh bắt "p304")
_TOKEN = re.compile(
    rf"(?<![\w.,])(\d[\d.,]*)\s*({_UNIT_ALT})?(?![\w])", re.IGNORECASE
)

_CURRENCY = re.compile(r"(vnđ|vnd|vn d|đồng|dong|đ|₫)", re.IGNORECASE)

# ngày tháng "14/8", "8/11", "11-08-2026" không phải tiền
_DATE = re.compile(r"(?<![\d.,])\d{1,2}\s*[/-]\s*\d{1,2}(?:\s*[/-]\s*\d{2,4})?(?![\d])")


def _strip_accents(s: str) -> str:
    table = {
        "ì": "i", "ỳ": "y", "ệ": "e", "ồ": "o", "ả": "a", "ỷ": "y",
        "í": "i", "ý": "y", "ê": "e", "ô": "o", "ơ": "o", "ư": "u",
        "à": "a", "á": "a", "ã": "a", "ạ": "a", "ă": "a", "â": "a",
    }
    return "".join(table.get(ch, ch) for ch in s)


def _normalize_digits(raw: str) -> Decimal | None:
    """Đổi '1.480.000', '1,5', '1.5', '500' -> Decimal."""
    s = raw.strip().strip(".,")
    if not s:
        return None
    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        parts = s.split(sep)
        if len(parts) > 2:
            s = "".join(parts)                    # 1.480.000 -> 1480000
        elif len(parts[-1]) == 3 and len(parts[0]) <= 3:
            s = "".join(parts)                    # 1.480 / 1,480 -> 1480
        else:
            s = parts[0] + "." + parts[1]         # 1,5 -> 1.5

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _apply_unit(value: Decimal, unit: str | None) -> Decimal:
    if not unit:
        return value
    factor = _UNITS.get(_strip_accents(unit.lower().strip()))
    return value * factor if factor else value


def _looks_like_identifier(raw: str) -> bool:
    """Chuỗi ngắn không đơn vị -> nhiều khả năng mã/ngày, không phải số tiền."""
    digits = sum(ch.isdigit() for ch in raw)
    return digits <= 3


def parse_money(text: str | int | float | None) -> int | None:
    """Trả về số nguyên đồng, hoặc None nếu không tìm thấy số tiền."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, int):
        return text
    if isinstance(text, float):
        return int(round(text))

    s = str(text).strip()
    if not s:
        return None
    s = _CURRENCY.sub(" ", s)

    # "14/8" là ngày, không phải tiền -> bỏ đi trước khi tìm số
    s = _DATE.sub(" ", s)

    m = _SHORTHAND.search(s)
    if m:
        value = _normalize_digits(f"{m.group(1)}.{m.group(3)}")
        if value is None:
            return None
        value = _apply_unit(value, m.group(2))
        return int(round(value))

    m = _TOKEN.search(s)
    if not m:
        return None
    raw, unit = m.group(1), m.group(2)
    stripped = s.strip()
    # "p304" / "14" -> không coi là tiền
    if (
        not unit
        and _looks_like_identifier(raw)
        and not any(c in s for c in ".,")
        and len(stripped) <= 4
        and len(raw) == len(stripped)
    ):
        return None
    value = _normalize_digits(raw)
    if value is None:
        return None
    value = _apply_unit(value, unit)
    if value == 0:
        return None
    return int(round(value))


def extract_money_tokens(text: str) -> list[int]:
    """Tìm mọi số tiền trong một chuỗi (dùng cho fallback không cần AI)."""
    out: list[int] = []
    rest = _CURRENCY.sub(" ", text or "")
    rest = _DATE.sub(" ", rest)

    def take_short(m: re.Match[str]) -> str:
        value = _normalize_digits(f"{m.group(1)}.{m.group(3)}")
        if value is not None:
            amount = int(round(_apply_unit(value, m.group(2))))
            if amount:
                out.append(amount)
        return " "

    rest = _SHORTHAND.sub(take_short, rest)

    for m in _TOKEN.finditer(rest):
        raw, unit = m.group(1), m.group(2)
        if not unit and _looks_like_identifier(raw):
            continue
        value = _normalize_digits(raw)
        if value is None:
            continue
        amount = int(round(_apply_unit(value, unit)))
        if amount:
            out.append(amount)
    return out


def format_money(value: int | float | Decimal | None) -> str:
    if value is None or value == "":
        return ""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return str(value)
    return f"{n:,}".replace(",", ".")
