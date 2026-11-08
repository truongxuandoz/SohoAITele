"""Test lệnh /ghi — đường đi tin cậy khi privacy mode đang bật."""

import asyncio

import pytest

import soho.bot as bot
from soho.ai import Item

GROUP_ID = -5591223295


class Msg:
    def __init__(self, text=""):
        self.text = text
        self.caption = None
        self.entities = []
        self.reply_to_message = None
        self.photo = None
        self.message_thread_id = None
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw))
        return self


class Chat:
    def __init__(self, cid, ctype="group", title="Soho AI Thu Chi"):
        self.id = cid
        self.type = ctype
        self.title = title


class User:
    def __init__(self, uid=6241137644, username="truongxuando"):
        self.id = uid
        self.username = username


class Upd:
    def __init__(self, msg, cid=GROUP_ID, ctype="group"):
        self.effective_message = msg
        self.effective_chat = Chat(cid, ctype)
        self.effective_user = User()
        self.message = msg


class BotStub:
    username = "SohoBoutiqueQNbot"
    id = 9021327534

    async def send_chat_action(self, chat_id, action):
        return None


class Ctx:
    def __init__(self, args=None):
        self.bot = BotStub()
        self.args = args or []
        self.error = None


@pytest.fixture(autouse=True)
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "PENDING", bot.PendingStore(tmp_path / "p.json"))
    monkeypatch.setattr(
        bot,
        "STORE",
        type("S", (), {"headers": list("abcde"), "info": lambda s: "x", "tail": lambda s, n=10: []})(),
    )
    monkeypatch.setattr(bot.config, "allowed_chats", {str(GROUP_ID)}, raising=False)
    monkeypatch.setattr(bot.config, "allowed_usernames", set(), raising=False)
    monkeypatch.setattr(
        bot, "parse_message", lambda *a, **k: ([Item(noi_dung="p304 tt", chi=1_480_000)], "")
    )


def test_ghi_with_args_works_in_group():
    """/ghi <nội dung> phải bóc được bút toán."""
    msg = Msg("/ghi p304 tt 1.480.000 chi soho")
    asyncio.run(bot.cmd_ghi(Upd(msg), Ctx(["p304", "tt", "1.480.000", "chi", "soho"])))
    assert msg.sent
    assert "1 bút toán" in msg.sent[-1][0]


def test_ghi_without_args_sends_force_reply_prompt():
    """/ghi trống -> gửi prompt kèm ForceReply, không crash."""
    msg = Msg("/ghi")
    asyncio.run(bot.cmd_ghi(Upd(msg), Ctx([])))
    assert msg.sent
    text, kw = msg.sent[-1]
    assert "bút toán" in text
    assert kw.get("reply_markup") is not None


def test_ghi_args_joined_with_spaces(monkeypatch):
    """context.args là list -> phải nối lại thành câu có dấu cách."""
    captured = {}

    def fake_parse(text, **kw):
        captured["text"] = text
        return [Item(noi_dung="x", chi=1000)], ""

    monkeypatch.setattr(bot, "parse_message", fake_parse)
    msg = Msg("/ghi p304 tt 1.480.000")
    asyncio.run(bot.cmd_ghi(Upd(msg), Ctx(["p304", "tt", "1.480.000"])))
    assert captured["text"] == "p304 tt 1.480.000"


def test_ghi_unauthorized_group():
    """Group lạ dùng /ghi -> báo chưa cấp quyền."""
    msg = Msg("/ghi p304 tt 1.480.000")
    asyncio.run(bot.cmd_ghi(Upd(msg, cid=-999999), Ctx(["p304", "tt", "1.480.000"])))
    assert "chưa được cấp quyền" in msg.sent[-1][0]


def test_bot_commands_include_ghi():
    """Menu lệnh phải có /ghi, nếu không user không biết cách dùng trong group."""
    names = [c for c, _ in bot.BOT_COMMANDS]
    assert "ghi" in names
    assert len(bot.BOT_COMMANDS) <= 20
    # Telegram giới hạn description 256 ký tự
    for cmd, desc in bot.BOT_COMMANDS:
        assert len(desc) <= 256
        assert cmd.islower()
