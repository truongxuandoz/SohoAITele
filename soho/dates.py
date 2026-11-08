"""Kiểm tra NGƯỢC ngày: ngày user nói có thực sự có trong sổ chưa.

Vấn đề: user ghi "P304 tt 500k" (không ngày) -> bot ghi vào sổ, nhưng nếu
dòng cuối của sổ đang là ngày khác thì bút toán bị hiểu sai ngày.

Yêu cầu của user:
  "kiểm tra với date thực tế khi user ghi ngày vào trong, và kiểm tra ngược
   lại xem có note ngày cho cột vào ngày đấy chưa, nếu chưa thì thêm vào"

Nghĩa là:
  - User có ghi ngày -> nếu sổ CHƯA có ngày đó -> phải ghi ngày vào cột A
    (không được bỏ trống, vì bỏ trống = thuộc ngày phía trên -> SAI ngày)
  - User không ghi ngày -> giữ nguyên (thuộc ngày của dòng cuối)
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# Từ chỉ ngày tương đối
RELATIVE_DAYS = {
    "hôm nay": 0, "hom nay": 0, "nay": 0,
    "hôm qua": 1, "hom qua": 1, "qua": 1,
    "hôm kia": 2, "hom kia": 2,
    "mai": -1, "ngày mai": -1, "ngay mai": -1,
}


def _strip_accents(text: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn")


def parse_relative_date(text: str, today: date | None = None) -> date | None:
    """Đọc ngày tương đối: 'hôm nay', 'hôm qua', '2 ngày trước'."""
    today = today or date.today()
    low = _strip_accents(text or "").lower().strip()

    for phrase, days_back in RELATIVE_DAYS.items():
        if _strip_accents(phrase) in low:
            return today - timedelta(days=days_back)

    m = re.search(r"(\d+)\s*ngay\s*(truoc|trước)", low)
    if m:
        return today - timedelta(days=int(m.group(1)))
    return None


def date_exists_in_sheet(store, target: date) -> tuple[bool, int | None]:
    """Ngày `target` đã có trong cột Ngày tháng của sổ chưa?

    Trả (có_không, dòng_chứa_ngày_đó).
    Dùng để quyết định: nếu CHƯA có thì phải ghi ngày vào cột A, không được
    để trống (trống = thuộc ngày của dòng phía trên -> bút toán bị sai ngày).
    """
    from .sheets import GoogleSheetStore

    store._refresh_bounds()  # noqa: SLF001
    start, end = store.data_region()
    if end < start:
        return False, None

    date_col = store.columns.get("ngay", 0)
    rows = store.read_range(start, end)

    target_key = target.isoformat()
    for offset, row in enumerate(rows):
        if date_col >= len(row):
            continue
        key = GoogleSheetStore._date_key(row[date_col])
        if key == target_key:
            return True, start + offset
    return False, None


def extract_date_from_text(text: str, today: date | None = None) -> str:
    """Trích ngày user viết trong tin nhắn: '9/11', '08/11/2026', 'hôm qua'.

    Trả '' nếu không thấy. Dùng khi AI không điền ngày nhưng user có nói.
    """
    today = today or date.today()
    text = text or ""

    # 'd/m' hoặc 'd/m/yyyy' — bắt cả khi dính liền chữ
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).strftime("%d/%m/%Y")
        except ValueError:
            pass

    rel = parse_relative_date(text, today)
    if rel:
        return rel.strftime("%d/%m/%Y")
    return ""


def ensure_date_present(items: list, store, user_text: str = "") -> list[str]:
    """Bổ sung ngày cho các bút toán nếu ngày đó CHƯA có trong sổ.

    Quy tắc:
      1. Nếu item đã có ngày -> giữ.
      2. Nếu item không có ngày nhưng user_text có ngày -> trích ra dùng.
      3. Nếu ngày đó CHƯA có trong sổ -> ghi ngày vào dòng đầu.
      4. Nếu ngày đó ĐÃ có -> để trống (thuộc ngày của dòng phía trên).

    Trả về danh sách ghi chú để hiện trong preview.
    """
    warnings: list[str] = []
    if not items:
        return warnings

    # Ngày đầu tiên tìm được: ưu tiên item, rồi trích từ text user
    first_key: str | None = None
    for it in items:
        if it.ngay_thang:
            first_key = it.ngay_thang
            break
    if not first_key:
        first_key = extract_date_from_text(user_text)
    if not first_key:
        return warnings

    from .sheets import GoogleSheetStore

    parsed = GoogleSheetStore._date_key(first_key)
    if not parsed:
        return warnings

    try:
        target = date.fromisoformat(parsed)
    except ValueError:
        return warnings

    # Ghi ngày vào dòng đầu nếu chưa có
    if not items[0].ngay_thang:
        items[0].ngay_thang = first_key

    exists, row = date_exists_in_sheet(store, target)
    pretty = target.strftime("%d/%m/%Y")
    if exists:
        warnings.append(f"Ngày {pretty} đã có trong sổ (dòng {row}) — cột Ngày để trống.")
    else:
        warnings.append(f"Ngày {pretty} chưa có trong sổ — sẽ ghi vào cột Ngày.")

    # Các dòng sau cùng ngày -> bỏ ngày (chỉ dòng đầu mang ngày)
    for it in items[1:]:
        if it.ngay_thang and GoogleSheetStore._date_key(it.ngay_thang) == parsed:
            it.ngay_thang = ""

    return warnings


def summarize_dates(items: list) -> str:
    """Tóm tắt ngày của lô bút toán để hiện trong preview."""
    if not items:
        return ""
    first = items[0].ngay_thang
    if not first:
        return "ngày: theo dòng cuối của sổ"
    same = all((i.ngay_thang or first) == first for i in items[:1])
    return f"ngày: {first}" if same else f"ngày: {first} (+ khác)"
