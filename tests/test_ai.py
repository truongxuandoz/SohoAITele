"""Test lớp AI bằng cách giả lập _chat (không gọi mạng)."""

import json

import soho.ai as ai


def test_sse_parsing_with_ping():
    body = (
        ": ping\n\n"
        'data: {"choices":[{"delta":{"content":"{\\"items\\":"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"[]}"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    assert ai._read_sse_text(body) == '{"items":[]}'


def test_sse_ignores_bad_json():
    body = 'data: {broken\n\ndata: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n'
    assert ai._read_sse_text(body) == "ok"


def test_extract_json_with_fence():
    raw = '```json\n{"items":[{"noi_dung":"x","chi":1000}]}\n```'
    data = ai._extract_json(raw)
    assert data["items"][0]["noi_dung"] == "x"


def test_extract_json_with_prose():
    raw = 'Đây là kết quả:\n{"items": []}\nHết.'
    assert ai._extract_json(raw) == {"items": []}


def test_parse_message_normalises(monkeypatch):
    payload = {
        "items": [
            {"ngay_thang": "11/8", "noi_dung": "p304 tt", "thu": "1.480.000", "chi": None, "ghi_chu": "soho"},
            {"noi_dung": "cước hotline", "thu": None, "chi": "159k", "ghi_chu": "soho"},
        ],
        "note": "ok",
    }
    monkeypatch.setattr(ai, "_chat", lambda *a, **k: json.dumps(payload))
    items, note = ai.parse_message("bất kỳ")
    assert len(items) == 2
    assert items[0].thu == 1_480_000
    assert items[1].chi == 159_000
    assert note == "ok"


def test_parse_message_drops_empty(monkeypatch):
    payload = {"items": [{"noi_dung": "", "thu": None, "chi": None}]}
    monkeypatch.setattr(ai, "_chat", lambda *a, **k: json.dumps(payload))
    items, _ = ai.parse_message("test")
    assert items == []


def test_parse_message_falls_back(monkeypatch):
    monkeypatch.setattr(ai, "_chat", lambda *a, **k: '{"items": []}')
    items, note = ai.parse_message("chi 159k cước hotline")
    assert len(items) == 1
    assert items[0].chi == 159_000
    assert "cách đọc" in note


def test_parse_message_bad_json(monkeypatch):
    monkeypatch.setattr(ai, "_chat", lambda *a, **k: "xin lỗi tôi không biết")
    items, _ = ai.parse_message("không có số nào ở đây")
    assert items == []


def test_parse_image_shape(monkeypatch):
    payload = {"items": [{"noi_dung": "p304 tt", "thu": 1_480_000, "ghi_chu": "soho"}]}
    monkeypatch.setattr(ai, "_chat", lambda *a, **k: json.dumps(payload))
    items, _ = ai.parse_image(b"\x89PNG fake", mime="image/png")
    assert items[0].thu == 1_480_000
    assert items[0].ghi_chu == "soho"
