"""Test hành vi bot trong GROUP: chỉ phản hồi khi @mention hoặc reply."""

import asyncio

import pytest

import soho.bot as bot
from soho.ai import Item

GROUP_ID = -5591223295
BOT_ID = 9021327534
BOT_USERNAME = "SohoBoutiqueQNbot"


class Entity:
    def __init__(self, type_, offset, length, user=None):
        self.type = type_
        self.offset = offset
        self.length = length
        self.user = user


class User:
    def __init__(self, uid, username=None, is_bot=False):
        self.id = uid
        self.username = username
        self.is_bot = is_bot


class Msg:
    def __init__(self, text="", entities=None, reply_to=None, photo=None, caption=None):
        self.text = text
        self.caption = caption
        self.entities = entities or []
        self.reply_to_message = reply_to
        self.photo = photo
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


class Upd:
    def __init__(self, msg, chat=None, user=None):
        self.effective_message = msg
        self.effective_chat = chat or Chat(GROUP_ID)
        self.effective_user = user or User(111, "truongxuando")
        self.message = msg


class BotStub:
    username = BOT_USERNAME
    id = BOT_ID

    def __init__(self):
        self.actions = []

    async def send_chat_action(self, chat_id, action):
        self.actions.append(action)


class Ctx:
    def __init__(self):
        self.bot = BotStub()
        self.args = []
        self.error = None


@pytest.fixture(autouse=True)
def setup_env(monkeypatch, tmp_path):
    monkeypatch.setattr(bot, "PENDING", bot.PendingStore(tmp_path / "p.json"))
    monkeypatch.setattr(bot, "STORE", type("S", (), {
        "headers": ["Ngày tháng", "Nội Dung", "Thu", "Chi", "ghi chú"],
        "info": lambda self: "Fake",
        "tail": lambda self, n=10: [],
        "append": lambda self, rows: list(range(1, len(rows) + 1)),
        "delete_last": lambda self, n: 0,
    })())
    monkeypatch.setattr(bot.config, "allowed_chats", {str(GROUP_ID)}, raising=False)
    monkeypatch.setattr(bot.config, "allowed_usernames", set(), raising=False)
    monkeypatch.setattr(
        bot, "parse_message", lambda *a, **k: ([Item(noi_dung="p304 tt", chi=1_480_000)], "")
    )


def test_group_ignores_unrelated_message():
    """Tin nhắn không gọi bot -> im lặng, không spam."""
    msg = Msg("hôm nay trời đẹp")
    asyncio.run(bot.on_group_text(Upd(msg), Ctx()))
    assert msg.sent == []


def test_group_responds_to_mention():
    """@SohoBoutiqueQNbot p304 tt 1.480.000 -> bóc bút toán."""
    text = f"@{BOT_USERNAME} p304 tt 1.480.000 chi soho"
    ent = Entity("mention", 0, len(BOT_USERNAME) + 1)
    msg = Msg(text, entities=[ent])
    asyncio.run(bot.on_group_text(Upd(msg), Ctx()))
    assert msg.sent, "phải trả lời khi được mention"
    assert "1 bút toán" in msg.sent[-1][0]


def test_group_mention_stripped_from_text(monkeypatch):
    """@mention không được lọt vào nội dung gửi AI."""
    captured = {}

    def fake_parse(text, **kw):
        captured["text"] = text
        return [Item(noi_dung="x", chi=1000)], ""

    monkeypatch.setattr(bot, "parse_message", fake_parse)
    text = f"@{BOT_USERNAME} p101 tt 350k"
    msg = Msg(text, entities=[Entity("mention", 0, len(BOT_USERNAME) + 1)])
    asyncio.run(bot.on_group_text(Upd(msg), Ctx()))

    assert "SohoBoutiqueQNbot" not in captured["text"]
    assert "p101" in captured["text"]


def test_group_responds_to_reply():
    """Reply vào tin của bot -> phản hồi."""
    bot_msg = Msg("preview cũ")
    bot_msg.from_user = User(BOT_ID, BOT_USERNAME, is_bot=True)
    msg = Msg("p301 coc 500k", reply_to=bot_msg)
    asyncio.run(bot.on_group_text(Upd(msg), Ctx()))
    assert msg.sent, "phải trả lời khi reply vào tin bot"


def test_group_reply_to_other_user_ignored():
    """Reply vào tin người khác (không phải bot) -> im lặng."""
    other = Msg("tin của người khác")
    other.from_user = User(999, "ai_do")
    msg = Msg("p301 coc 500k", reply_to=other)
    asyncio.run(bot.on_group_text(Upd(msg), Ctx()))
    assert msg.sent == []


def test_group_unauthorized_chat():
    """Group lạ -> báo chưa cấp quyền, kèm chat_id."""
    text = f"@{BOT_USERNAME} p304 tt 1.480.000"
    msg = Msg(text, entities=[Entity("mention", 0, len(BOT_USERNAME) + 1)])
    upd = Upd(msg, chat=Chat(-123456789, "group", "Group lạ"))
    asyncio.run(bot.on_group_text(upd, Ctx()))
    assert msg.sent
    assert "chưa được cấp quyền" in msg.sent[-1][0]
    assert "-123456789" in msg.sent[-1][0]


def test_group_empty_after_mention_asks():
    """Chỉ mention, không nội dung -> hỏi lại, không im."""
    msg = Msg(f"@{BOT_USERNAME}", entities=[Entity("mention", 0, len(BOT_USERNAME) + 1)])
    asyncio.run(bot.on_group_text(Upd(msg), Ctx()))
    assert msg.sent
    assert "bút toán gì" in msg.sent[-1][0]


def test_cmd_id_shows_group_hint():
    """Lệnh /id trong group phải in chat_id âm + hướng dẫn copy."""
    msg = Msg("/id")
    asyncio.run(bot.cmd_id(Upd(msg), Ctx()))
    text = msg.sent[-1][0]
    assert str(GROUP_ID) in text
    assert "ALLOWED_CHAT_ID" in text


def test_private_chat_unaffected_by_group_handler():
    """Handler group không được bắt tin ở chat riêng."""
    msg = Msg("p304 tt 1.480.000")
    upd = Upd(msg, chat=Chat(6241137644, "private", None))
    before = len(msg.sent)
    asyncio.run(bot.on_text(upd, Ctx()))
    assert len(msg.sent) > before
