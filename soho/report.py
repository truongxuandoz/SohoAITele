"""Trả lời câu hỏi về sổ: đọc dữ liệu thật rồi để AI tổng hợp.

Tách khỏi bot.py vì đây là logic nghiệp vụ, dùng lại được cho web/CLI.

Nguyên tắc: AI KHÔNG được tự bịa số. Mọi con số phải lấy từ `read_range()`
của sổ. AI chỉ diễn giải câu hỏi và trình bày kết quả.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

from .ai import _chat
from .money import format_money

# Số dòng tối đa gửi cho AI. Sổ ~700 dòng, gửi hết vẫn trong ngưỡng model,
# nhưng cắt bớt để phản hồi nhanh và rẻ.
MAX_ROWS_TO_AI = 400

ANSWER_PROMPT = """Bạn là trợ lý kế toán cho cửa hàng Soho Boutique.
Bạn nhận được DỮ LIỆU SỔ THẬT (các dòng thu chi) và một CÂU HỎI.

QUY TẮC BẮT BUỘC:
- CHỈ dùng số liệu có trong phần dữ liệu được cung cấp. TUYỆT ĐỐI không bịa số.
- Nếu dữ liệu không đủ để trả lời, nói rõ "sổ chưa có dữ liệu cho..." thay vì đoán.
- Trả lời ngắn gọn bằng tiếng Việt, thân thiện, dùng bullet khi liệt kê.
- Số tiền format kiểu Việt Nam: 1.480.000đ
- Khi liệt kê nhiều dòng, nêu tổng cộng ở cuối.
- Không giải thích bạn là AI, không chào hỏi dài dòng.

Định dạng: văn bản thuần (Telegram hiển thị). Có thể dùng • và dấu -.
"""


def _parse_vn_date(value: Any) -> date | None:
    """Đọc cột 'Ngày tháng' của sổ.

    Sổ thật dùng 2 dạng:
      - Google Sheets DATE cell -> UNFORMATTED_VALUE trả số serial (46265)
      - text người dùng gõ ("13/8", "31/8")
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        # Serial date của Google Sheets / Excel: 1 = 1899-12-31 (Excel epoch)
        if 1 <= float(value) <= 100000:
            try:
                from datetime import timedelta

                return date(1899, 12, 30) + timedelta(days=int(value))
            except (ValueError, OverflowError):
                return None
        return None

    text = str(value).strip()
    if not text:
        return None
    # Serial dạng chuỗi
    if re.fullmatch(r"\d{5}(\.0+)?", text):
        try:
            from datetime import timedelta

            return date(1899, 12, 30) + timedelta(days=int(float(text)))
        except (ValueError, OverflowError):
            return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = date.today().year
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _row_to_dict(row: list[Any], columns: dict[str, int]) -> dict[str, Any]:
    def get(key: str, default: int) -> Any:
        idx = columns.get(key, default)
        return row[idx] if idx < len(row) else None

    from .sheets import _to_number

    d = _parse_vn_date(get("ngay", 0))
    return {
        "ngay": d.isoformat() if d else "",
        "noi_dung": str(get("noi_dung", 1) or "").strip(),
        "thu": _to_number(get("thu", 2)),
        "chi": _to_number(get("chi", 3)),
        "ghi_chu": str(get("ghi_chu", 4) or "").strip(),
    }


def _is_summary_row(row: list[Any]) -> bool:
    """Nhận diện dòng tổng/ghi chú chen giữa vùng dữ liệu.

    Sổ thật có dòng như "Tổng" (R312), "Tổng cuối tháng 7" (R313) nằm ngay
    trong vùng dữ liệu. Không được tính chúng là bút toán, và phải CẮT
    fill-down ngày tại đó.

    PHẢI CHÍNH XÁC: bút toán thật có thể chứa chữ "còn lại" giữa câu
    (vd "P 101 tt còn lại" 350.000). Chỉ coi là dòng tổng khi ô NỘI DUNG
    BẮT ĐẦU bằng từ khoá tổng, hoặc ô đầu (cột A) bắt đầu bằng "Tổng".
    """
    noi_dung = str(row[1] if len(row) > 1 else "" or "").strip().lower()
    cot_a = str(row[0] if row else "" or "").strip().lower()

    starts = ("tổng", "tong", "còn lại", "con lai", "lưu ý", "luu y", "thiếu")
    if noi_dung.startswith(starts) or cot_a.startswith(starts):
        return True

    # "Còn lại" đứng riêng ở cột Thu (dòng R677 của sổ)
    return any(
        str(cell or "").strip().lower() in ("tổng", "tong", "còn lại", "con lai")
        for cell in row[:3]
    )


def collect_rows(store, limit: int = MAX_ROWS_TO_AI) -> list[dict[str, Any]]:
    """Lấy các dòng có số tiền, mới nhất trước.

    QUAN TRỌNG về cột ngày: sổ ghi ngày MỘT LẦN ở dòng đầu mỗi ngày, các dòng
    sau trong cùng ngày để trống cột A. Nên phải "fill down" ngày — NHƯNG phải
    cắt fill-down khi gặp dòng tổng/ghi chú, vì sổ có khối "Tổng cuối tháng"
    chen giữa; nếu không, dòng đầu tháng sau sẽ bị gán nhầm ngày tháng trước.
    """
    store._refresh_bounds()  # noqa: SLF001
    start, end = store.data_region()
    if end < start:
        return []

    first = max(start, end - limit + 1)
    # Đọc LÙI thêm vài dòng để biết ngày của dòng đầu cửa sổ.
    lookback = 15
    read_from = max(start, first - lookback)
    rows = store.read_range(read_from, end)
    cols = getattr(store, "columns", {}) or {}

    out: list[dict[str, Any]] = []
    last_date: str = ""
    for offset, row in enumerate(rows):
        row_idx = read_from + offset

        if _is_summary_row(row):
            # Dòng tổng/ghi chú: không phải bút toán, và CẮT fill-down.
            last_date = ""
            continue

        d = _row_to_dict(row, cols)
        if d["ngay"]:
            last_date = d["ngay"]
        elif last_date:
            d["ngay"] = last_date

        if row_idx < first:
            continue
        if d["thu"] or d["chi"] or d["noi_dung"]:
            out.append(d)
    return out


def month_summary(store, year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """Tổng thu/chi của một tháng, tính hoàn toàn bằng code (không qua AI).

    Dùng cho /xem — cần con số CHÍNH XÁC, không để model làm tròn.
    """
    today = date.today()
    year = year or today.year
    month = month or today.month

    rows = collect_rows(store, limit=2000)
    matched = []
    for r in rows:
        if not r["ngay"]:
            continue
        try:
            d = date.fromisoformat(r["ngay"])
        except ValueError:
            continue
        if d.year == year and d.month == month:
            matched.append({**r, "_d": d})

    total_thu = sum(r["thu"] for r in matched)
    total_chi = sum(r["chi"] for r in matched)

    # Nhóm theo ghi_chu để thấy dòng tiền từng kênh (soho/tm/kim)
    by_tag: dict[str, dict[str, int]] = {}
    for r in matched:
        tag = (r["ghi_chu"] or "(không nhãn)").lower()
        bucket = by_tag.setdefault(tag, {"thu": 0, "chi": 0, "count": 0})
        bucket["thu"] += r["thu"]
        bucket["chi"] += r["chi"]
        bucket["count"] += 1

    # Nhóm theo ngày để thấy dòng tiền hiện tại
    by_day: dict[str, dict[str, int]] = {}
    for r in matched:
        bucket = by_day.setdefault(r["ngay"], {"thu": 0, "chi": 0})
        bucket["thu"] += r["thu"]
        bucket["chi"] += r["chi"]

    no_date = [r for r in rows if not r["ngay"]]
    return {
        "year": year,
        "month": month,
        "count": len(matched),
        "thu": total_thu,
        "chi": total_chi,
        "net": total_thu - total_chi,
        "by_tag": by_tag,
        "by_day": dict(sorted(by_day.items())),
        "rows": matched,
        "no_date_count": len(no_date),
        "total_rows_scanned": len(rows),
    }


def format_month_summary(s: dict[str, Any]) -> str:
    """Trình bày kết quả /xem bằng HTML cho Telegram."""
    lines = [f"<b>📊 Tháng {s['month']:02d}/{s['year']}</b>", ""]
    if not s["count"]:
        lines.append("Chưa có bút toán nào có ngày trong tháng này.")
        if s["no_date_count"]:
            lines.append(
                f"(Có {s['no_date_count']} dòng không ghi ngày — "
                "dùng /ghi kèm ngày, ví dụ: <code>/ghi 13/8 p304 tt 500k</code>)"
            )
        return "\n".join(lines)

    lines.append(f"Tổng thu : <b>{format_money(s['thu'])}</b>")
    lines.append(f"Tổng chi : <b>{format_money(s['chi'])}</b>")
    net = s["net"]
    sign = "+" if net >= 0 else "−"
    lines.append(f"Còn lại  : <b>{sign}{format_money(abs(net))}</b>")
    lines.append(f"<i>{s['count']} bút toán</i>")

    if len(s["by_tag"]) > 1:
        lines.append("")
        lines.append("<b>Theo nhãn</b>")
        for tag, v in sorted(s["by_tag"].items(), key=lambda kv: -(kv[1]["thu"] + kv[1]["chi"])):
            bits = []
            if v["thu"]:
                bits.append(f"thu {format_money(v['thu'])}")
            if v["chi"]:
                bits.append(f"chi {format_money(v['chi'])}")
            lines.append(f"• {tag}: {' · '.join(bits) or '0'} ({v['count']})")

    if len(s["by_day"]) > 1:
        lines.append("")
        lines.append("<b>Dòng tiền hiện tại</b>")
        running = 0
        for day, v in s["by_day"].items():
            running += v["thu"] - v["chi"]
            try:
                label = date.fromisoformat(day).strftime("%d/%m")
            except ValueError:
                label = day
            lines.append(f"• {label}: {format_money(running)}")

    if s["no_date_count"]:
        lines.append("")
        lines.append(f"<i>⚠️ {s['no_date_count']} dòng không có ngày, không tính vào tháng.</i>")
    return "\n".join(lines)


def answer_question(store, question: str) -> str:
    """Trả lời câu hỏi tự do dựa trên dữ liệu sổ thật.

    QUAN TRỌNG về hiệu năng: KHÔNG gửi toàn bộ sổ cho AI. Sổ ~650 dòng, gửi hết
    làm prompt quá lớn -> gateway timeout sau 60s (đã gặp thật).

    Thay vào đó:
      1. Tính sẵn thống kê bằng code (chính xác, không phụ thuộc model)
      2. Gửi bản tóm tắt theo tháng/nhãn + 40 dòng gần nhất làm ví dụ
    Model chỉ diễn giải và trình bày, không tự cộng số.
    """
    rows = collect_rows(store, limit=3000)
    if not rows:
        return "Sổ chưa có dữ liệu để trả lời."

    prompt_data = {
        "tong_quan": _compact_summary(rows),
        "cac_dong_gan_nhat": [
            {
                "ngay": r["ngay"],
                "noi_dung": r["noi_dung"][:60],
                "thu": r["thu"] or None,
                "chi": r["chi"] or None,
                "ghi_chu": r["ghi_chu"],
            }
            for r in rows[-40:]
        ],
    }

    user_block = (
        f"HÔM NAY: {date.today().strftime('%d/%m/%Y')}\n\n"
        f"DỮ LIỆU SỔ (đã tính sẵn bằng code — số này CHÍNH XÁC, dùng đúng số này):\n"
        f"{json.dumps(prompt_data, ensure_ascii=False)}\n\n"
        f"CÂU HỎI: {question.strip()}"
    )

    content = _chat(
        [
            {"role": "system", "content": ANSWER_PROMPT},
            {"role": "user", "content": user_block},
        ]
    )
    text = (content or "").strip()
    return text or "Mình chưa trả lời được câu này, bạn thử hỏi cụ thể hơn."


def _compact_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Tóm tắt gọn để gửi AI: theo tháng, theo nhãn. Giữ dưới ~2KB."""
    by_month: dict[str, dict[str, int]] = {}
    by_tag: dict[str, dict[str, int]] = {}
    for r in rows:
        ym = r["ngay"][:7] or "(không ngày)"
        m = by_month.setdefault(ym, {"thu": 0, "chi": 0, "so_dong": 0})
        m["thu"] += r["thu"]
        m["chi"] += r["chi"]
        m["so_dong"] += 1

        tag = (r["ghi_chu"] or "(không nhãn)").lower()
        t = by_tag.setdefault(tag, {"thu": 0, "chi": 0, "so_dong": 0})
        t["thu"] += r["thu"]
        t["chi"] += r["chi"]
        t["so_dong"] += 1

    total_thu = sum(r["thu"] for r in rows)
    total_chi = sum(r["chi"] for r in rows)
    top_tags = sorted(by_tag.items(), key=lambda kv: -(kv[1]["thu"] + kv[1]["chi"]))[:8]
    return {
        "so_dong_tong": len(rows),
        "tong_thu_toan_so": total_thu,
        "tong_chi_toan_so": total_chi,
        "chenh_lech_toan_so": total_thu - total_chi,
        "theo_thang": {
            ym: {
                "thu": v["thu"],
                "chi": v["chi"],
                "con_lai": v["thu"] - v["chi"],
                "so_dong": v["so_dong"],
            }
            for ym, v in sorted(by_month.items())
        },
        "theo_nhan": {
            tag: {"thu": v["thu"], "chi": v["chi"], "so_dong": v["so_dong"]}
            for tag, v in top_tags
        },
    }


def looks_like_question(text: str) -> bool:
    """Đoán xem tin nhắn có phải câu hỏi (để trả lời thay vì bóc bút toán)."""
    low = text.lower().strip()
    if "?" in low:
        return True
    keywords = (
        "kiểm tra", "kiem tra", "xem", "thống kê", "thong ke", "tổng", "tong",
        "bao nhiêu", "bao nhieu", "còn lại", "con lai", "dòng tiền", "dong tien",
        "tháng này", "thang nay", "hôm nay", "hom nay", "tuần này", "tuan nay",
        "liệt kê", "liet ke", "báo cáo", "bao cao", "tính", "tinh",
    )
    return any(k in low for k in keywords)
