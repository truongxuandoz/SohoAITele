"""Test logic bot không cần Telegram thật: preview, keyboard, guard."""

from soho.ai import Item
from soho.bot import _keyboard, _preview_text


def test_preview_totals():
    items = [
        Item(noi_dung="p304 tt", thu=1_480_000, ghi_chu="soho"),
        Item(noi_dung="cước hotline", chi=159_000, ghi_chu="soho"),
    ]
    text = _preview_text(items, "ok")
    assert "Có 2 bút toán" in text
    assert "1.480.000" in text
    assert "159.000" in text
    assert "Tổng thu" in text and "Tổng chi" in text


def test_preview_escapes_html():
    text = _preview_text([Item(noi_dung="p101 & <b>coc</b>", chi=1000)], "")
    assert "&amp;" in text
    assert "&lt;b&gt;" in text


def test_keyboard_callbacks():
    kb = _keyboard()
    datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert datas == ["commit", "edit", "cancel"]


def test_item_as_row_shape():
    row = Item(noi_dung="a", ngay_thang="11/8", thu=1000, chi=None, ghi_chu="tm").as_row()
    assert row == ["11/8", "a", 1000, "", "tm"]
    assert len(row) == 5


def test_application_wiring():
    import soho.bot as bot

    bot.config.telegram_token = "123456:TESTTOKEN_not_real"
    app = bot.build_application()
    assert app is not None
