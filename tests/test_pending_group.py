"""Test các lỗi 'Phiên chờ đã hết hạn' gặp thật trong group.

Ba nguyên nhân đã tìm ra từ log thật:
  1. Khoá pending theo chat_id trần -> trong group nhiều người ghi đè nhau
  2. Bấm nút 2 lần -> Telegram trả BadRequest 'Message is not modified'
  3. Dashboard ở process khác chưa thấy pending do bot ghi -> phải đọc lại file
"""

from __future__ import annotations

import asyncio

import pytest

import soho.bot as bot
from soho.ai import Item
from soho.pending import Pending, PendingStore

GROUP = -5591223295
BOT_ID = 9021327534


# ────────────────────────── pending store ──────────────────────────


class TestPendingKeys:
    def test_two_users_same_group_do_not_overwrite(self, tmp_path):
        """Lỗi thật: Kim và Dō cùng gửi /ghi trong group.

        Khoá theo chat_id trần -> cái sau ghi đè cái trước, bấm nút
        trên preview cũ báo 'hết hạn'.
        """
        store = PendingStore(tmp_path / "p.json")
        store.put(GROUP, Pending(items=[Item(noi_dung="cua Kim", chi=1000)]), message_id=101)
        store.put(GROUP, Pending(items=[Item(noi_dung="cua Do", chi=2000)]), message_id=102)

        kim = store.get(GROUP, 101)
        do = store.get(GROUP, 102)
        assert kim is not None, "preview của Kim phải còn"
        assert kim.items[0].noi_dung == "cua Kim"
        assert do is not None
        assert do.items[0].noi_dung == "cua Do"

    def test_pop_only_removes_target_message(self, tmp_path):
        """Ghi pending của Kim không được xoá pending của Dō."""
        store = PendingStore(tmp_path / "p.json")
        store.put(GROUP, Pending(items=[Item(noi_dung="kim")]), message_id=201)
        store.put(GROUP, Pending(items=[Item(noi_dung="do")]), message_id=202)

        store.pop(GROUP, 201)
        assert store.get(GROUP, 201) is None
        assert store.get(GROUP, 202) is not None

    def test_old_key_format_still_readable(self, tmp_path):
        """Dữ liệu cũ lưu theo khoá chat_id trần vẫn phải đọc được."""
        store = PendingStore(tmp_path / "p.json")
        store.put(GROUP, Pending(items=[Item(noi_dung="cu")]))  # không message_id
        assert store.get(GROUP) is not None
        assert store.get(GROUP, 999) is not None  # fallback khoá trần

    def test_rereads_file_written_by_another_process(self, tmp_path):
        """Bot ghi pending, dashboard/process khác chưa thấy -> phải đọc lại file."""
        path = tmp_path / "p.json"
        reader = PendingStore(path)          # process "đọc"
        writer = PendingStore(path)          # process "ghi"
        writer.put(GROUP, Pending(items=[Item(noi_dung="moi")]), message_id=301)

        got = reader.get(GROUP, 301)
        assert got is not None, "phải đọc lại file khi RAM chưa có"
        assert got.items[0].noi_dung == "moi"

    def test_expired_pending_still_returns_none(self, tmp_path):
        store = PendingStore(tmp_path / "p.json")
        p = Pending(items=[Item(noi_dung="x")], created_at=0)  # rất cũ
        store.put(GROUP, p, message_id=401)
        assert store.get(GROUP, 401) is None


# ────────────────────────── callback handler ──────────────────────────


class Msg:
    def __init__(self, text="", message_id=1):
        self.text = text
        self.caption = None
        self.entities = []
        self.reply_to_message = None
        self.photo = None
        self.message_thread_id = None
        self.message_id = message_id
        self.sent = []
        self.edits = []

    async def reply_text(self, text, **kw):
        self.sent.append(text)
        return Msg(text, message_id=self.message_id + 1)

    async def edit_text(self, text, **kw):
        self.edits.append(text)


class Query:
    def __init__(self, data, message):
        self.data = data
        self.message = message

    async def answer(self):
        return None

    async def edit_message_text(self, text, **kw):
        self.message.edits.append(text)


class Chat:
    id = GROUP
    type = "group"
    title = "Soho AI Thu Chi"


class User:
    id = 6241137644
    username = "truongxuando"
    is_bot = False


class Ctx:
    def __init__(self):
        self.bot = type("B", (), {"username": "SohoBoutiqueQNbot", "id": BOT_ID})()
        self.args = []


class U:
    def __init__(self, msg, data=None):
        self.effective_message = msg
        self.effective_chat = Chat()
        self.effective_user = User()
        self.message = msg
        if data is not None:
            self.callback_query = Query(data, msg)


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "PENDING", PendingStore(tmp_path / "p.json"))
    monkeypatch.setattr(bot.config, "allowed_chats", {str(GROUP)}, raising=False)
    monkeypatch.setattr(bot.config, "allowed_usernames", set(), raising=False)
    written = []

    class FakeStore:
        headers = list("abcde")

        def info(self):
            return "fake"

        def tail(self, n=10):
            return []

        def append(self, rows):
            written.append(rows)
            return [len(written) + 663]

    monkeypatch.setattr(bot, "STORE", FakeStore())
    return written


class TestCallback:
    def test_commit_then_second_click_does_not_duplicate(self, store):
        """Bấm nút 2 lần chỉ được ghi 1 lần."""
        msg = Msg(message_id=500)
        bot.PENDING.put(GROUP, Pending(items=[Item(noi_dung="p304", chi=5000)]), message_id=500)

        asyncio.run(bot.on_callback(U(msg, "commit"), Ctx()))
        assert len(store) == 1
        assert any("Đã ghi" in e for e in msg.edits)

        # Bấm lần 2 trên cùng tin nhắn
        msg2 = Msg(message_id=500)
        asyncio.run(bot.on_callback(U(msg2, "commit"), Ctx()))
        assert len(store) == 1, "không được ghi trùng"
        # Lần 2 rơi vào nhánh pending=None -> phải trấn an, không doạ "hết hạn"
        assert any("Không có gì bị mất" in e for e in msg2.edits)

    def test_not_modified_error_is_swallowed(self, store, monkeypatch):
        """Telegram 'Message is not modified' không được làm sập handler."""
        from telegram.error import BadRequest

        msg = Msg(message_id=501)
        bot.PENDING.put(GROUP, Pending(items=[Item(noi_dung="x", chi=100)]), message_id=501)

        async def boom(text, **kw):
            raise BadRequest("Message is not modified: ...")

        q = Query("commit", msg)
        q.edit_message_text = boom
        upd = U(msg, "commit")
        upd.callback_query = q

        asyncio.run(bot.on_callback(upd, Ctx()))  # không được raise
        assert len(store) == 1

    def test_missing_pending_message_reassures_user(self, store):
        """Pending không có -> nói rõ không mất dữ liệu, đừng chỉ 'hết hạn'."""
        msg = Msg(message_id=999)
        asyncio.run(bot.on_callback(U(msg, "commit"), Ctx()))
        text = msg.edits[-1]
        assert "Không có gì bị mất" in text
        assert "/undo" in text

    def test_buttons_removed_after_commit(self, store):
        """Sau khi ghi phải bỏ nút để tránh bấm lại."""
        msg = Msg(message_id=502)
        bot.PENDING.put(GROUP, Pending(items=[Item(noi_dung="x", chi=100)]), message_id=502)

        captured = {}
        q = Query("commit", msg)

        async def spy(text, **kw):
            captured.update(kw)
            msg.edits.append(text)

        q.edit_message_text = spy
        upd = U(msg, "commit")
        upd.callback_query = q
        asyncio.run(bot.on_callback(upd, Ctx()))

        assert captured.get("reply_markup") is None

    def test_append_failure_restores_pending(self, store, monkeypatch):
        """Ghi sổ lỗi -> phải giữ pending để bấm lại, không bắt user dán lại."""
        msg = Msg(message_id=503)
        bot.PENDING.put(GROUP, Pending(items=[Item(noi_dung="x", chi=100)]), message_id=503)

        class Broken:
            headers = list("abcde")

            def info(self):
                return "x"

            def tail(self, n=10):
                return []

            def append(self, rows):
                raise RuntimeError("Sheets API 500")

        monkeypatch.setattr(bot, "STORE", Broken())
        asyncio.run(bot.on_callback(U(msg, "commit"), Ctx()))

        assert any("Lỗi ghi sổ" in e for e in msg.edits)
        assert bot.PENDING.get(GROUP, 503) is not None, "pending phải được trả lại"
