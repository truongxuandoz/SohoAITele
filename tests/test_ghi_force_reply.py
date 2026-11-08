"""Test luồng /ghi -> ForceReply -> user reply nhiều dòng (đường đi cho group)."""

import asyncio

import pytest

import soho.bot as bot
from soho.ai import Item

GROUP_ID = -5591223295
BOT_ID = 9021327534


class Msg:
    def __init__(self, text="", reply_to=None):
        self.text = text
        self.caption = None
        self.entities = []
        self.reply_to_message = reply_to
        self.photo = None
        self.message_thread_id = None
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append((text, kw))
        return self


class FromUser:
    def __init__(self, uid, is_bot=False):
        self.id = uid
        self.is_bot = is_bot


class Chat:
    def __init__(self, cid=-5591223295, ctype="group", title="Soho AI Thu Chi"):
        self.id = cid
        self.type = ctype
        self.title = title


class User:
    id = 6241137644
    username = "truongxuando"


class BotStub:
    username = "SohoBoutiqueQNbot"
    id = BOT_ID

    async def send_chat_action(self, chat_id, action):
        return None


class Upd:
    def __init__(self, msg):
        self.effective_message = msg
        self.effective_chat = Chat()
        self.effective_user = User()
        self.message = msg


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


def test_ghi_no_args_sends_force_reply():
    """/ghi không args -> gửi ForceReply để xin nội dung."""
    msg = Msg("/ghi")
    asyncio.run(bot.cmd_ghi(Upd(msg), Ctx([])))
    assert msg.sent
    _text, kw = msg.sent[-1]
    markup = kw.get("reply_markup")
    assert markup is not None
    assert type(markup).__name__ == "ForceReply"


def test_ghi_with_args_processes_directly(monkeypatch):
    """/ghi p304 tt 1.480.000 -> xử lý ngay, không cần ForceReply."""
    captured = {}

    def fake_parse(text, **kw):
        captured["text"] = text
        return [Item(noi_dung="p304 tt", chi=1_480_000)], ""

    monkeypatch.setattr(bot, "parse_message", fake_parse)
    msg = Msg("/ghi p304 tt 1.480.000 chi soho")
    asyncio.run(bot.cmd_ghi(Upd(msg), Ctx(["p304", "tt", "1.480.000", "chi", "soho"])))
    assert captured["text"] == "p304 tt 1.480.000 chi soho"
    assert msg.sent
    assert "1 bút toán" in msg.sent[-1][0]


def test_reply_to_bot_multiline_works(monkeypatch):
    """User reply vào tin bot với nhiều dòng -> bot nhận và bóc."""
    captured = {}

    def fake_parse(text, **kw):
        captured["text"] = text
        return [Item(noi_dung=f"x{i}", chi=1000) for i in range(3)], ""

    monkeypatch.setattr(bot, "parse_message", fake_parse)

    bot_msg = Msg("Gửi nội dung bút toán...")
    bot_msg.from_user = FromUser(BOT_ID, is_bot=True)

    reply = Msg("11/8\np304 tt 990.000\nsuối 10k chi tm", reply_to=bot_msg)
    asyncio.run(bot.on_group_text(Upd(reply), Ctx()))

    assert "11/8" in captured.get("text", "")
    assert reply.sent
    assert "3 bút toán" in reply.sent[-1][0]


def test_reply_to_other_person_ignored():
    """Reply vào tin người khác -> im lặng."""
    other = Msg("tin người khác")
    other.from_user = FromUser(999, is_bot=False)
    reply = Msg("p304 tt 990.000", reply_to=other)
    asyncio.run(bot.on_group_text(Upd(reply), Ctx()))
    assert reply.sent == []
