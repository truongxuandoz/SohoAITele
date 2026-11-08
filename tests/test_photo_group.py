"""Test ảnh trong GROUP — lỗi thật: "nhắn riêng thì được, group thì không".

Nguyên nhân: on_group_text kiểm tra @mention TRƯỚC khi kiểm tra photo.
Ảnh không thể chứa mention dạng text (entities=[]), nên điều kiện
`if not (mentioned or replied_to_me): return` chặn ảnh luôn.
"""

from __future__ import annotations

import asyncio

import pytest

import soho.bot as bot
from soho.ai import Item

GROUP = -5591223295
BOT_ID = 9021327534
BOT_USER = "SohoBoutiqueQNbot"


class Photo:
    def __init__(self, file_id="f1", w=800, h=600):
        self.file_id = file_id
        self.width = w
        self.height = h


class Msg:
    def __init__(self, text="", caption=None, photos=None, reply_to=None, message_id=1):
        self.text = text
        self.caption = caption
        self.entities = []
        self.reply_to_message = reply_to
        self.photo = photos
        self.message_thread_id = None
        self.message_id = message_id
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(text)
        return Msg(message_id=self.message_id + 1)


class TgFile:
    def __init__(self, raw=b"\xff\xd8\xff" + b"x" * 100, mime="image/jpeg"):
        self.mime_type = mime
        self._raw = raw

    async def download_as_bytearray(self):
        return bytearray(self._raw)


class BotStub:
    username = BOT_USER
    id = BOT_ID

    def __init__(self, raw=b"\xff\xd8\xff" + b"x" * 100, mime="image/jpeg"):
        self._file = TgFile(raw, mime)
        self.actions = []

    async def send_chat_action(self, chat_id, action):
        self.actions.append(action)

    async def get_file(self, file_id):
        return self._file


class Chat:
    id = GROUP
    type = "group"
    title = "Soho AI Thu Chi"


class User:
    id = 6241137644
    username = "truongxuando"
    is_bot = False


class Ctx:
    def __init__(self, bot_stub=None):
        self.bot = bot_stub or BotStub()
        self.args = []


class U:
    def __init__(self, msg):
        self.effective_message = msg
        self.effective_chat = Chat()
        self.effective_user = User()
        self.message = msg


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "PENDING", bot.PendingStore(tmp_path / "p.json"))
    monkeypatch.setattr(
        bot,
        "STORE",
        type(
            "S",
            (),
            {
                "headers": list("abcde"),
                "info": lambda s: "x",
                "tail": lambda s, n=10: [],
                "append": lambda s, r: [664],
            },
        )(),
    )
    monkeypatch.setattr(bot.config, "allowed_chats", {str(GROUP)}, raising=False)
    monkeypatch.setattr(bot.config, "allowed_usernames", set(), raising=False)


class TestPhotoInGroup:
    def test_photo_without_mention_is_processed(self, monkeypatch):
        """LỖI CHÍNH: ảnh trong group không có @mention vẫn phải được xử lý.

        Ảnh không thể chứa mention text -> nếu bắt mention thì ảnh luôn bị bỏ.
        """
        called = {}

        def fake_parse_image(raw, mime="image/jpeg", caption=""):
            called["raw"] = raw
            called["mime"] = mime
            return [Item(noi_dung="p203 302", thu=960_000)], "đọc từ ảnh"

        monkeypatch.setattr(bot, "parse_image", fake_parse_image)

        msg = Msg(photos=[Photo()])  # entities=[] vì ảnh không có text
        asyncio.run(bot.on_group_text(U(msg), Ctx()))

        assert "raw" in called, "ảnh phải được gửi tới model"
        assert msg.sent, "phải trả lời user"
        assert "1 bút toán" in msg.sent[-1]

    def test_photo_with_caption_works(self, monkeypatch):
        """Ảnh kèm caption (dùng làm chỉ dẫn cho model)."""
        captured = {}

        def fake_parse_image(raw, mime="image/jpeg", caption=""):
            captured["caption"] = caption
            return [Item(noi_dung="x", chi=1000)], ""

        monkeypatch.setattr(bot, "parse_image", fake_parse_image)

        msg = Msg(caption="hoá đơn chuyển khoản", photos=[Photo()])
        asyncio.run(bot.on_group_text(U(msg), Ctx()))
        assert captured["caption"] == "hoá đơn chuyển khoản"
        assert msg.sent

    def test_text_without_mention_still_ignored(self):
        """Text thường không mention vẫn phải IM LẶNG (không spam group)."""
        msg = Msg(text="hôm nay trời đẹp")
        asyncio.run(bot.on_group_text(U(msg), Ctx()))
        assert msg.sent == []

    def test_photo_in_private_chat_works(self, monkeypatch):
        """Chat riêng vẫn phải chạy (đã chạy trước đó, đừng làm hỏng)."""
        monkeypatch.setattr(
            bot, "parse_image", lambda raw, mime="image/jpeg", caption="": ([Item(noi_dung="p", chi=5000)], "")
        )
        msg = Msg(photos=[Photo()])
        upd = U(msg)
        upd.effective_chat = type("C", (), {"id": 6241137644, "type": "private", "title": None})()
        asyncio.run(bot.on_photo(upd, Ctx()))
        assert msg.sent


class TestMimeDetection:
    """Ảnh phải gửi đúng mime, nếu không model từ chối."""

    def test_png_detected(self):
        assert bot._guess_mime(b"\x89PNG\r\n\x1a\n" + b"x" * 50) == "image/png"

    def test_jpeg_detected(self):
        assert bot._guess_mime(b"\xff\xd8\xff" + b"x" * 50) == "image/jpeg"

    def test_webp_detected(self):
        raw = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"x" * 20
        assert bot._guess_mime(raw) == "image/webp"

    def test_gif_detected(self):
        assert bot._guess_mime(b"GIF89a" + b"x" * 20) == "image/gif"

    def test_octet_stream_falls_back(self):
        """Telegram đôi khi báo application/octet-stream -> phải đoán được."""
        raw = b"\x89PNG\r\n\x1a\n" + b"x" * 50
        assert bot._guess_mime(raw, "application/octet-stream") == "image/png"

    def test_unknown_defaults_to_jpeg(self):
        assert bot._guess_mime(b"\x00\x01\x02\x03", None) == "image/jpeg"
