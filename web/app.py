"""[TUỲ CHỌN] Bot cho website: FastAPI + widget chat, dùng lại soho.ai và soho.sheets.

Chạy:
    pip install fastapi uvicorn
    uvicorn web.app:app --reload --port 8000

Mở http://127.0.0.1:8000 → có khung chat. Logic bóc bút toán và ghi sổ
y hệt bot Telegram, chỉ khác lớp giao diện.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from soho.ai import parse_message
from soho.money import format_money
from soho.sheets import build_store

app = FastAPI(title="SoHo AI Web")

_store = None
_cache: dict[str, list[dict]] = {}  # chat session id -> bút toán đang chờ


def _get_store():
    global _store
    if _store is None:
        _store = build_store(2)
    return _store


class ChatIn(BaseModel):
    session_id: str = "default"
    text: str


class CommitIn(BaseModel):
    session_id: str = "default"


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    store = _get_store()
    items, note = parse_message(body.text, context_rows=store.tail(8), headers=store.headers)
    if not items:
        return {"reply": "Mình chưa thấy số tiền nào. Thử: p304 tt 1.480.000 chi soho", "items": []}

    _cache[body.session_id] = [i.as_row() for i in items]

    lines = [f"Có {len(items)} bút toán chờ ghi sổ:"]
    for idx, item in enumerate(items, 1):
        lines.append(f"{idx}. {item.pretty()}")
    lines.append("")
    lines.append("Bấm Ghi sổ để ghi, hoặc Huỷ.")
    return {"reply": "\n".join(lines), "items": [i.pretty() for i in items], "note": note}


@app.post("/api/commit")
def commit(body: CommitIn) -> dict:
    rows = _cache.pop(body.session_id, None)
    if not rows:
        return {"reply": "Không có gì để ghi."}
    written = _get_store().append(rows)
    return {"reply": f"Đã ghi {len(written)} dòng vào sổ (dòng {written[0]}–{written[-1]})."}


@app.post("/api/cancel")
def cancel(body: CommitIn) -> dict:
    _cache.pop(body.session_id, None)
    return {"reply": "Đã huỷ."}


@app.get("/api/tail")
def tail() -> dict:
    store = _get_store()
    return {
        "headers": store.headers,
        "rows": [
            [format_money(c) if i in (2, 3) and str(c).replace(".", "").isdigit() else str(c) for i, c in enumerate(r)]
            for r in store.tail(10)
        ],
    }


INDEX_HTML = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return INDEX_HTML
