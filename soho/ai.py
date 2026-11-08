"""Gọi AI gateway (OpenAI-compatible) để bóc tin nhắn thành các dòng bút toán."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests

from .config import config
from .money import format_money, parse_money

SYSTEM_PROMPT = """Bạn là kế toán cho một cửa hàng xây dựng/thi công nhỏ ở Việt Nam.
Nhiệm vụ: đọc tin nhắn tiếng Việt (có thể viết tắt, sai dấu, không dấu) của người dùng
và bóc thành các dòng bút toán để ghi vào sổ Excel/Google Sheet.

Cấu trúc sổ (mỗi dòng là một bút toán):
- ngay_thang : ngày tháng, giữ đúng như người dùng viết ("11/8", "8/11", "hôm qua"). Nếu người dùng không nói, để "".
- noi_dung   : nội dung/ diễn giải ngắn gọn (vd "p304 tt", "cước hotline", "hoàn cọc cho khách", "p101 tt").
- thu        : số tiền THU VÀO (khách trả, hoàn ứng về...), đơn vị đồng, số nguyên. Không có thì null.
- chi        : số tiền CHI RA (trả nhà cung cấp, trả công, mua vật tư...), số nguyên. Không có thì null.
- ghi_chu    : nhãn phân loại ngắn theo thói quen của sổ, thường là "soho", "tm", "kim". Không rõ thì "".

QUY TẮC SỐ TIỀN (rất quan trọng):
- "1.480.000" hoặc "1,480,000" = 1480000. "159k" = 159000. "1tr2" = 1200000. "2 triệu" = 2000000.
- "500 nghìn" = 500000. "1,5tr" = 1500000. Luôn trả về số nguyên đồng, không có dấu chấm/phẩy.
- Từ ngữ chỉ chiều tiền: "thu", "khách trả", "nhận", "thu tiền", "hoàn ứng" -> thu.
  "chi", "trả", "mua", "thanh toán", "cọc", "tạm ứng", "công" -> chi.
- Nếu câu nói rõ "thu" hoặc "chi" thì theo đúng câu. Nếu mơ hồ và chỉ có một số tiền:
  mặc định là chi (đa số bút toán trong sổ là chi phí thi công), trừ khi có dấu hiệu thu.
- Một tin nhắn có thể chứa NHIỀU bút toán (nhiều dòng, nhiều số tiền) -> trả về nhiều item.

QUY TẮC KHÁC:
- Không tự bịa số tiền. Không thấy số tiền thì bỏ trống cả thu và chi.
- "nội dung" phải giữ từ khoá kỹ thuật (p304, p101, coc 14/8, mibibar...) vì đó là mã công trình.
- "ghi_chu": nếu tin nhắn không ghi nhãn, hãy suy ra từ các dòng tương tự trong phần ngữ cảnh sổ
  (ví dụ dòng cùng mã công trình hoặc cùng người mua trước đó dùng nhãn gì). Không chắc thì để "".
- Chỉ trả về JSON thuần, không giải thích, không markdown.

Định dạng trả về:
{"items":[{"ngay_thang":"","noi_dung":"","thu":null,"chi":null,"ghi_chu":""}],"note":"ghi chú ngắn cho người dùng (tuỳ chọn)"}
"""


@dataclass
class Item:
    noi_dung: str = ""
    ngay_thang: str = ""
    thu: int | None = None
    chi: int | None = None
    ghi_chu: str = ""

    def as_row(self) -> list[Any]:
        return [
            self.ngay_thang,
            self.noi_dung,
            self.thu if self.thu else "",
            self.chi if self.chi else "",
            self.ghi_chu,
        ]

    def pretty(self, index: int | None = None) -> str:
        head = f"{index}. " if index is not None else ""
        bits = [head + (self.noi_dung or "(không nội dung)")]
        if self.ngay_thang:
            bits.append(f"ngày {self.ngay_thang}")
        if self.thu:
            bits.append(f"THU {format_money(self.thu)}")
        if self.chi:
            bits.append(f"CHI {format_money(self.chi)}")
        if self.ghi_chu:
            bits.append(f"[{self.ghi_chu}]")
        return " · ".join(bits)


def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(round(value))
    parsed = parse_money(str(value))
    return parsed or None


def _to_item(raw: dict[str, Any]) -> Item:
    return Item(
        noi_dung=str(raw.get("noi_dung") or raw.get("noi_dung_") or "").strip(),
        ngay_thang=str(raw.get("ngay_thang") or "").strip(),
        thu=_coerce_int(raw.get("thu")),
        chi=_coerce_int(raw.get("chi")),
        ghi_chu=str(raw.get("ghi_chu") or "").strip(),
    )


def _chat(messages: list[dict[str, Any]], temperature: float = 0.1, attempts: int = 3) -> str:
    """Gọi gateway. Gateway này LUÔN trả SSE (kể cả khi không set stream=true),
    nên phải đọc stream rồi ghép delta. Có retry vì gateway đôi khi chậm/timeout."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _chat_once(messages, temperature)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_error = exc
            if attempt < attempts:
                import time as _time

                _time.sleep(2 * attempt)
                continue
            raise RuntimeError(
                f"AI gateway không phản hồi sau {attempts} lần thử ({type(exc).__name__}). "
                "Thử lại sau ít phút, hoặc tăng AI_TIMEOUT trong .env."
            ) from exc
    raise RuntimeError(f"AI gateway lỗi: {last_error}")


def _chat_once(messages: list[dict[str, Any]], temperature: float) -> str:
    url = f"{config.ai_base_url}/chat/completions"
    payload = {
        "model": config.ai_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 2000,
    }
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {config.ai_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        },
        json=payload,
        timeout=(15, config.ai_timeout),
        stream=True,
    )
    if resp.status_code >= 400:
        detail = resp.text[:300]
        raise RuntimeError(f"AI gateway lỗi {resp.status_code}: {detail}")

    content_type = (resp.headers.get("content-type") or "").lower()

    if "event-stream" in content_type:
        return _read_sse(resp)

    body = resp.text
    try:
        data = resp.json()
    except ValueError as exc:
        # đôi khi header sai nhưng nội dung vẫn là SSE
        if body.lstrip().startswith(("data:", ":")):
            return _read_sse_text(body)
        raise RuntimeError(f"Phản hồi AI không đọc được: {body[:300]}") from exc

    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Phản hồi AI không hợp lệ: {str(data)[:300]}") from exc


def _read_sse(resp: requests.Response) -> str:
    parts: list[str] = []
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if line.startswith(":"):  # ": ping"
            continue
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk in ("", "[DONE]"):
            if chunk == "[DONE]":
                break
            continue
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            piece = delta.get("content")
            if piece:
                parts.append(piece)
    return "".join(parts)


def _read_sse_text(body: str) -> str:
    parts: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk == "[DONE]":
            break
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            piece = delta.get("content")
            if piece:
                parts.append(piece)
    return "".join(parts)


def _context_block(context_rows: list[list[str]], headers: list[str]) -> str:
    if not context_rows:
        return "Sổ hiện đang trống."
    lines = [" | ".join(headers)]
    for row in context_rows:
        lines.append(" | ".join("" if c in (None, "") else str(c) for c in row))
    return "Vài dòng gần nhất trong sổ (để học cách viết nội dung và ghi chú):\n" + "\n".join(lines)


def parse_message(
    text: str,
    context_rows: list[list[str]] | None = None,
    headers: list[str] | None = None,
    today: date | None = None,
) -> tuple[list[Item], str]:
    """Trả về (danh sách bút toán, ghi chú của AI)."""
    today = today or date.today()
    headers = headers or ["Ngày tháng", "Nội Dung", "Thu", "Chi", "ghi chú"]

    user_block = (
        f"Hôm nay là {today.strftime('%d/%m/%Y')}.\n"
        f"{_context_block(context_rows or [], headers)}\n\n"
        f"Tin nhắn cần bóc:\n\"\"\"\n{text.strip()}\n\"\"\""
    )

    content = _chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_block},
        ]
    )
    data = _extract_json(content) or {}

    items: list[Item] = []
    raw_items = data.get("items")
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    for raw in raw_items or []:
        if isinstance(raw, dict):
            item = _to_item(raw)
            if item.noi_dung or item.thu or item.chi:
                items.append(item)

    if not items:  # AI trả về "không có gì" -> thử bóc thô
        fallback = naive_parse(text)
        if fallback:
            return fallback, "AI không bóc được, đã dùng cách đọc số tiền đơn giản."

    return items, str(data.get("note") or "")


def naive_parse(text: str) -> list[Item]:
    """Fallback không cần AI: lấy số tiền lớn nhất làm chi, phần chữ làm nội dung."""
    from .money import extract_money_tokens

    money = extract_money_tokens(text)
    cleaned = re.sub(r"\d[\d.,]*\s*(k|ng|nghìn|ngàn|tr|triệu|tỷ|ty|trieu|m|b)?", " ", text, flags=re.I)
    cleaned = re.sub(r"\b(vnđ|vnd|đồng|dong)\b", " ", cleaned, flags=re.I)
    noi_dung = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    if not money:
        return []
    is_income = bool(re.search(r"\bthu\b|\bkhách trả\b|\bnhận\b", text, re.I))
    amount = max(money)
    item = Item(noi_dung=noi_dung, thu=amount if is_income else None, chi=None if is_income else amount)
    return [item]


VISION_PROMPT = """Bạn là kế toán cho một cửa hàng xây dựng/thi công nhỏ ở Việt Nam.
Đọc ảnh sổ tay / hoá đơn / bảng kê (có thể chữ viết tay, tiếng Việt) và bóc từng dòng thành bút toán.

Trả về JSON thuần, không markdown, không giải thích:
{"items":[{"ngay_thang":"","noi_dung":"","thu":null,"chi":null,"ghi_chu":""}],"note":""}

Quy tắc:
- noi_dung: giữ nguyên mã công trình / từ khoá kỹ thuật viết trong ảnh (p304, coc 14/8, mibibar...).
- thu / chi: số nguyên đồng. "1.480.000" -> 1480000. Cột nào có số thì điền cột đó.
- ngay_thang: chỉ điền khi ảnh ghi rõ ngày cho dòng đó.
- ghi_chu: nhãn ngắn trong ảnh (soho / tm / kim), không có thì "".
- Dòng nào không đọc được số tiền thì bỏ qua, đừng bịa.
"""


def parse_image(
    image_bytes: bytes, mime: str = "image/jpeg", caption: str = ""
) -> tuple[list[Item], str]:
    """Đọc ảnh sổ tay/hoá đơn -> danh sách bút toán."""
    b64 = base64.b64encode(image_bytes).decode()
    user_text = caption.strip() or "Đọc ảnh này và bóc thành các bút toán."
    content = _chat(
        [
            {"role": "system", "content": VISION_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ]
    )
    data = _extract_json(content) or {}
    raw_items = data.get("items") or []
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    items = [_to_item(r) for r in raw_items if isinstance(r, dict)]
    items = [i for i in items if i.noi_dung or i.thu or i.chi]
    return items, str(data.get("note") or "")

