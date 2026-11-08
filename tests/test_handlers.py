"""Test handler bot với đối tượng Telegram giả — không cần token, không cần mạng."""

import asyncio

import pytest

import soho.bot as bot
from soho.ai import Item


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.caption = None
        self.sent: list[dict] = []

    async def reply_text(self, text, **kwargs):
        self.sent.append({"text": text, **kwargs})
        return self

    @property
    def last(self) -> dict:
        return self.sent[-1]


FAKE_CHAT_ID = 123456


class FakeChat:
    def __init__(self, chat_id=FAKE_CHAT_ID):
        self.id = chat_id
        self.type = "private"


class FakeUser:
    def __init__(self, username="tester"):
        self.username = username


class FakeUpdate:
    def __init__(self, text="", chat_id=FAKE_CHAT_ID):
        self.effective_message = FakeMessage(text)
        self.effective_chat = FakeChat(chat_id)
        self.effective_user = FakeUser()
        self.message = self.effective_message


class FakeBot:
    username = "SohoBoutiqueQNbot"
    id = 9021327534

    def __init__(self):
        self.actions: list[str] = []

    async def send_chat_action(self, chat_id, action):
        self.actions.append(str(action))


class FakeContext:
    def __init__(self, args=None):
        self.bot = FakeBot()
        self.args = args or []
        self.error = None


class FakeStore:
    headers = ["Ngày tháng", "Nội Dung", "Thu", "Chi", "ghi chú"]

    def __init__(self):
        self.rows: list[list] = [["", "p304 tt", "1480000", "", "soho"]]
        self.appended: list[list] = []

    def info(self):
        return "Fake Sheet / SoHo"

    def tail(self, limit=10):
        return self.rows[-limit:]

    def append(self, rows):
        self.appended.extend(rows)
        start = len(self.rows) + 3
        self.rows.extend(rows)
        return list(range(start, start + len(rows)))

    def delete_last(self, count):
        removed = min(count, len(self.rows))
        del self.rows[len(self.rows) - removed :]
        return removed


@pytest.fixture(autouse=True)
def _allow_test_chat(monkeypatch):
    """.env thật có ALLOWED_CHAT_ID của máy dev -> ép về chat_id test cho mọi test."""
    monkeypatch.setattr(bot.config, "allowed_chats", {str(FAKE_CHAT_ID)}, raising=False)
    monkeypatch.setattr(bot.config, "allowed_usernames", set(), raising=False)


@pytest.fixture()
def store(monkeypatch, tmp_path):
    fake = FakeStore()
    monkeypatch.setattr(bot, "STORE", fake)
    monkeypatch.setattr(bot, "PENDING", bot.PendingStore(tmp_path / "pending.json"))
    return fake


def test_setup_ok(store):
    assert store.info().startswith("Fake Sheet")


@pytest.mark.parametrize("command", ["start", "help", "id"])
def test_simple_commands(store, command):
    update, ctx = FakeUpdate(), FakeContext()
    handler = {"start": bot.cmd_start, "help": bot.cmd_help, "id": bot.cmd_id}[command]
    asyncio.run(handler(update, ctx))
    assert update.effective_message.sent


def test_text_flow_creates_pending(store, monkeypatch):
    monkeypatch.setattr(bot, "parse_message", lambda *a, **k: ([Item(noi_dung="p304 tt", chi=1_480_000)], "ok"))
    update, ctx = FakeUpdate("p304 tt 1.480.000"), FakeContext()

    asyncio.run(bot.on_text(update, ctx))

    msg = update.effective_message.last
    assert "1 bút toán" in msg["text"]
    assert msg["reply_markup"] is not None
    assert bot.PENDING.get(update.effective_chat.id) is not None
    assert ctx.bot.actions  # có hiện "typing"


def test_commit_writes_rows(store, monkeypatch):
    monkeypatch.setattr(bot, "parse_message", lambda *a, **k: ([Item(noi_dung="p304 tt", thu=990_000, ngay_thang="11/8", ghi_chu="soho")], ""))
    update = FakeUpdate("p304 tt 990k")
    ctx = FakeContext()
    asyncio.run(bot.on_text(update, ctx))

    class FakeQuery:
        data = "commit"

        async def answer(self):
            pass

        async def edit_message_text(self, text, **kwargs):
            self.text = text

    cb_update = FakeUpdate()
    cb_update.callback_query = FakeQuery()
    asyncio.run(bot.on_callback(cb_update, FakeContext()))

    assert store.appended == [["11/8", "p304 tt", 990_000, "", "soho"]]
    assert "Đã ghi 1 dòng" in cb_update.callback_query.text


def test_cancel_discards(store, monkeypatch):
    monkeypatch.setattr(bot, "parse_message", lambda *a, **k: ([Item(noi_dung="x", chi=1000)], ""))
    update = FakeUpdate("x 1k")
    ctx = FakeContext()
    asyncio.run(bot.on_text(update, ctx))

    class FakeQuery:
        data = "cancel"

        async def answer(self):
            pass

        async def edit_message_text(self, text, **kwargs):
            self.text = text

    cb_update = FakeUpdate()
    cb_update.callback_query = FakeQuery()
    asyncio.run(bot.on_callback(cb_update, FakeContext()))

    assert store.appended == []
    assert bot.PENDING.get(update.effective_chat.id) is None
    assert "Đã huỷ" in cb_update.callback_query.text


def test_no_money_replies(store, monkeypatch):
    monkeypatch.setattr(bot, "parse_message", lambda *a, **k: ([], ""))
    update = FakeUpdate("xin chào")
    ctx = FakeContext()
    asyncio.run(bot.on_text(update, ctx))
    assert "chưa thấy số tiền" in update.effective_message.last["text"]


def test_too_many_items(store, monkeypatch):
    monkeypatch.setattr(bot, "config", type("C", (), {"max_items": 2, **{k: getattr(bot.config, k) for k in ("allowed_chats", "allowed_usernames", "timezone")}})())
    monkeypatch.setattr(bot, "parse_message", lambda *a, **k: ([Item(noi_dung=f"x{i}", chi=1000) for i in range(5)], ""))
    update = FakeUpdate("x")
    ctx = FakeContext()
    asyncio.run(bot.on_text(update, ctx))
    assert "Tối đa 2 dòng" in update.effective_message.last["text"]


def test_ai_error_is_reported(store, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("AI chết")

    monkeypatch.setattr(bot, "parse_message", boom)
    update = FakeUpdate("x 1k")
    ctx = FakeContext()
    asyncio.run(bot.on_text(update, ctx))
    assert "Lỗi gọi AI" in update.effective_message.last["text"]


def test_store_none_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "STORE", None)
    monkeypatch.setattr(bot, "PENDING", bot.PendingStore(tmp_path / "p.json"))
    update = FakeUpdate("x 1k")
    ctx = FakeContext()
    asyncio.run(bot.on_text(update, ctx))
    assert "chưa kết nối" in update.effective_message.last["text"]


def test_tail_and_undo(store):
    update = FakeUpdate()
    ctx = FakeContext()
    asyncio.run(bot.cmd_tail(update, ctx))
    assert "p304 tt" in update.effective_message.last["text"]

    update2 = FakeUpdate()
    asyncio.run(bot.cmd_undo(update2, FakeContext(["1"])))
    assert "Đã xoá 1 dòng" in update2.effective_message.last["text"]


def test_unauthorized_chat(store, monkeypatch):
    monkeypatch.setattr(bot, "config", type("C", (), {"allowed_chats": {"999"}, "allowed_usernames": set(), "max_items": 20, "telegram_token": "x", "ai_api_key": "x", "ai_base_url": "x", "sheet_backend": "x", "spreadsheet_id": "", "credentials_path": lambda self: None, "timezone": "Asia/Ho_Chi_Minh"})())
    update = FakeUpdate("x 1k", chat_id=111)
    ctx = FakeContext()
    asyncio.run(bot.on_text(update, ctx))
    assert "chưa được cấp quyền" in update.effective_message.last["text"]
