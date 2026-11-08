"""Bot Telegram: nhận tin nhắn -> AI bóc -> xem trước -> ghi vào sổ."""

from __future__ import annotations

import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .ai import Item, parse_image, parse_message
from .config import config
from .money import format_money
from .pending import Pending, PendingStore
from .sheets import build_store

log = logging.getLogger(__name__)

PENDING = PendingStore(config.data_dir() / "pending.json")
STORE = None  # khởi tạo trong post_init, tránh crash lúc import
HEADER_ROW = 2

HELP_TEXT = """<b>SoHo AI</b> — ghi sổ tự động bằng AI

Gõ tin nhắn bình thường, bot bóc thành bút toán rồi chờ bạn bấm nút ghi sổ.

<b>Trong GROUP — dùng lệnh /ghi</b>
Telegram không cho bot đọc tin thường trong group, nên phải dùng lệnh:
<code>/ghi p304 tt 1.480.000 chi soho</code>

<b>Chat riêng — gõ tự do</b>
<code>p304 tt 1.480.000 chi soho</code>
<code>hôm nay chi 159k cước hotline, thu 1tr2 hoàn ứng</code>

<b>Nhiều dòng một lúc</b> (chỉ ở chat riêng) — dán cả khối:
<code>11/8
p304 tt 990.000
suối 10k
102, 202, 302 mibibar 70k</code>

<b>Lệnh</b>
/ghi – ghi sổ (dùng được trong group)
/id – xem chat_id
/tail – 10 dòng cuối của sổ
/undo – xoá dòng bot vừa ghi
/help – trợ giúp

Gửi <b>ảnh</b> sổ tay / hoá đơn cũng được (ở chat riêng)."""


# ────────────────────────── helpers ──────────────────────────


def _esc(text: str) -> str:
    """Escape HTML: an toàn hơn Markdown khi nội dung có _ * [ ] ( ) ~ ` >."""
    return html.escape(str(text or ""), quote=False)


def _is_allowed(update: Update) -> bool:
    if not config.allowed_chats and not config.allowed_usernames:
        return True  # chưa cấu hình -> cho phép (chỉ nên dùng khi test)
    chat = update.effective_chat
    user = update.effective_user
    if chat and str(chat.id) in config.allowed_chats:
        return True
    return bool(user and user.username and user.username.lower() in config.allowed_usernames)


def _today_date():
    """Ngày hôm nay theo TIMEZONE trong .env (máy chủ có thể ở múi giờ khác)."""
    try:
        return datetime.now(ZoneInfo(config.timezone)).date()
    except Exception:  # pragma: no cover
        return datetime.now().date()


def _preview_text(items: list[Item], note: str) -> str:
    lines = [f"<b>Có {len(items)} bút toán chờ ghi sổ:</b>", ""]
    total_thu = sum(i.thu or 0 for i in items)
    total_chi = sum(i.chi or 0 for i in items)
    for idx, item in enumerate(items, 1):
        lines.append(f"<b>{idx}.</b> {_esc(item.pretty())}")
    lines.append("")
    if total_thu:
        lines.append(f"Tổng thu: <b>{format_money(total_thu)}</b>")
    if total_chi:
        lines.append(f"Tổng chi: <b>{format_money(total_chi)}</b>")
    if note:
        lines.append(f"<i>AI: {_esc(note)}</i>")
    lines.append("")
    lines.append("Bấm <b>Ghi sổ</b> để ghi, hoặc <b>Sửa</b> để dán lại cho đúng.")
    return "\n".join(lines)


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Ghi sổ", callback_data="commit"),
                InlineKeyboardButton("✏️ Sửa", callback_data="edit"),
                InlineKeyboardButton("❌ Huỷ", callback_data="cancel"),
            ]
        ]
    )


async def _guard(update: Update) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    # Log mọi chat_id gặp được -> dễ điền ALLOWED_CHAT_ID mà không cần hỏi user.
    log.info(
        "chat_id=%s type=%s user=@%s",
        getattr(chat, "id", None),
        getattr(chat, "type", None),
        getattr(user, "username", None),
    )
    if _is_allowed(update):
        return True
    log.warning(
        "Từ chối truy cập: chat=%s user=%s",
        getattr(chat, "id", None),
        getattr(user, "username", None),
    )
    if update.effective_message:
        await update.effective_message.reply_text(
            "⛔ Chat này chưa được cấp quyền.\n"
            f"chat_id của bạn: <code>{_esc(getattr(chat, 'id', '?'))}</code>\n"
            "Thêm số này vào ALLOWED_CHAT_ID trong file .env rồi khởi động lại bot.",
            parse_mode=ParseMode.HTML,
        )
    return False


# ────────────────────────── commands ──────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    info = STORE.info() if STORE else "chưa kết nối"
    await update.effective_message.reply_text(
        HELP_TEXT + f"\n\nĐang ghi vào: <code>{_esc(info)}</code>", parse_mode=ParseMode.HTML
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xem chat_id. Không qua _guard để chat lạ cũng lấy được ID."""
    log.info("HANDLER cmd_id chạy")
    chat = update.effective_chat
    user = update.effective_user
    topic = getattr(update.effective_message, "message_thread_id", None)
    lines = [
        f"chat_id: <code>{chat.id}</code>",
        f"type: <code>{_esc(chat.type)}</code>",
    ]
    if getattr(chat, "title", None):
        lines.append(f"title: <code>{_esc(chat.title)}</code>")
    if topic:
        lines.append(f"topic/thread id: <code>{topic}</code>")
    lines.append(f"username: <code>@{_esc(getattr(user, 'username', '') or '')}</code>")
    if chat.type in ("group", "supergroup"):
        lines.append("")
        lines.append("Dán dòng này vào ALLOWED_CHAT_ID trong .env:")
        lines.append(f"<code>{chat.id}</code>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_ghi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ghi sổ trong group — dùng ForceReply để nhận được nội dung nhiều dòng.

    Vì sao cần: privacy mode chặn tin thường trong group, bot chỉ nhận LỆNH
    và tin REPLY vào tin của bot. Nên:
      1. User gõ /ghi  ->  bot gửi ô nhập (ForceReply)
      2. User reply vào ô đó, dán bao nhiêu dòng cũng được
      3. Telegram coi đó là "reply meant for this bot" -> bot nhận được

    Cũng hỗ trợ gõ tắt một dòng: /ghi p304 tt 1.480.000 chi soho
    """
    if not await _guard(update):
        return

    text = " ".join(context.args or []).strip()
    if text:
        await _handle_text(update, context, text)
        return

    from telegram import ForceReply

    await update.effective_message.reply_text(
        "Gửi nội dung bút toán — dán nhiều dòng cũng được.\n"
        "Ví dụ:\n"
        "11/8\n"
        "p304 tt 990.000\n"
        "suối 10k chi tm",
        reply_markup=ForceReply(selective=True),
    )


async def cmd_tail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if STORE is None:
        await update.effective_message.reply_text("Sổ chưa kết nối được, kiểm tra .env.")
        return
    try:
        rows = STORE.tail(10)
    except Exception as exc:
        await update.effective_message.reply_text(f"⚠️ Không đọc được sổ: {exc}")
        return
    if not rows:
        await update.effective_message.reply_text("Sổ đang trống.")
        return
    lines = ["<b>10 dòng gần nhất:</b>", "<pre>"]
    for row in rows:
        lines.append(_esc(" | ".join("" if c is None else str(c) for c in row)))
    lines.append("</pre>")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if STORE is None:
        await update.effective_message.reply_text("Sổ chưa kết nối được.")
        return
    count = int(context.args[0]) if context.args and context.args[0].isdigit() else 1
    try:
        removed = STORE.delete_last(count)
    except Exception as exc:
        await update.effective_message.reply_text(f"⚠️ Không xoá được: {exc}")
        return
    await update.effective_message.reply_text(
        f"Đã xoá {removed} dòng cuối." if removed else "Không có dòng nào để xoá."
    )


# ────────────────────────── core flow ──────────────────────────


async def _send_preview(message, items: list[Item], note: str) -> None:
    await message.reply_text(
        _preview_text(items, note), reply_markup=_keyboard(), parse_mode=ParseMode.HTML
    )


async def _handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if not await _guard(update):
        return
    message = update.effective_message
    chat_id = update.effective_chat.id

    if STORE is None:
        await message.reply_text("Sổ chưa kết nối được, kiểm tra file .env rồi khởi động lại bot.")
        return

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    context_rows: list[list[str]] = []
    headers = ["Ngày tháng", "Nội Dung", "Thu", "Chi", "ghi chú"]
    try:
        context_rows = STORE.tail(8)
        headers = STORE.headers or headers
    except Exception as exc:  # pragma: no cover
        log.warning("Không đọc được tail: %s", exc)

    try:
        items, note = parse_message(
            text, context_rows=context_rows, headers=headers, today=_today_date()
        )
    except Exception as exc:
        log.exception("Lỗi AI")
        await message.reply_text(f"⚠️ Lỗi gọi AI: {exc}")
        return

    if not items:
        await message.reply_text(
            "Mình chưa thấy số tiền nào trong tin nhắn.\n"
            "Thử lại kiểu: <code>p304 tt 1.480.000 chi soho</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(items) > config.max_items:
        await message.reply_text(
            f"⚠️ Tối đa {config.max_items} dòng mỗi lần. Tin nhắn này có {len(items)} dòng."
        )
        return

    PENDING.put(chat_id, Pending(items=items, note=note))
    await _send_preview(message, items, note)


async def on_group_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tin nhắn trong GROUP có @mention bot hoặc reply vào tin của bot.

    Telegram bật privacy mode mặc định: bot CHỈ nhận được
      - lệnh /command
      - tin có @mention tới bot
      - tin reply vào tin của bot
    Muốn nhận MỌI tin trong group thì phải tắt privacy mode qua BotFather
    (/setprivacy -> Disable), rồi gỡ bot khỏi group và add lại.
    """
    await log_chat_id(update, context)

    message = update.effective_message
    if not message:
        return

    # Chỉ xử lý khi bot thực sự được gọi tên
    me_username = (context.bot.username or "").lower()
    me_id = context.bot.id

    mentioned = False
    for ent in message.entities or []:
        if ent.type == "mention":
            frag = (message.text or "")[ent.offset : ent.offset + ent.length]
            if frag.lstrip("@").lower() == me_username:
                mentioned = True
                break
        elif ent.type == "text_mention" and ent.user and ent.user.id == me_id:
            mentioned = True
            break

    replied_to_me = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == me_id
    )

    if not (mentioned or replied_to_me):
        return  # không gọi bot -> im lặng, không spam group

    text = message.text or message.caption or ""
    if me_username:
        text = text.replace(f"@{context.bot.username}", " ")
    text = " ".join(text.split()).strip()

    if message.photo:
        await on_photo(update, context)
        return

    if not text:
        await message.reply_text("Dạ, bạn cần ghi bút toán gì ạ? Ví dụ: p304 tt 1.480.000 chi soho")
        return

    await _handle_text(update, context, text)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = message.text or ""

    # Trong group, tin nhắn thường bắt đầu bằng "@BotUsername bút toán..."
    # Phải bóc mention ra, nếu không AI sẽ coi "@SohoBoutiqueQNbot" là nội dung.
    me = context.bot.username
    if me:
        text = text.replace(f"@{me}", " ")
    text = " ".join(text.split()).strip()

    if not text:
        return
    await _handle_text(update, context, text)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ảnh (sổ tay, hoá đơn) -> gửi base64 cho model vision."""
    if not await _guard(update):
        return
    message = update.effective_message
    chat_id = update.effective_chat.id
    caption = message.caption or ""

    photo = message.photo[-1]
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    try:
        file = await context.bot.get_file(photo.file_id)
        raw = bytes(await file.download_as_bytearray())
    except Exception as exc:
        log.exception("Không tải được ảnh")
        await message.reply_text(f"⚠️ Không tải được ảnh: {exc}")
        return

    try:
        items, note = parse_image(raw, mime="image/jpeg", caption=caption)
    except Exception as exc:
        log.exception("Lỗi AI vision")
        await message.reply_text(f"⚠️ Không đọc được ảnh: {exc}")
        return

    if not items:
        await message.reply_text("Không bóc được dòng nào từ ảnh này. Thử ảnh rõ hơn / chụp thẳng góc.")
        return

    if len(items) > config.max_items:
        await message.reply_text(
            f"⚠️ Tối đa {config.max_items} dòng mỗi lần. Ảnh này có {len(items)} dòng."
        )
        return

    note = note or "đọc từ ảnh"
    PENDING.put(chat_id, Pending(items=items, note=note))
    await _send_preview(message, items, note)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_allowed(update):
        await query.edit_message_text("⛔ Không có quyền.")
        return

    chat_id = update.effective_chat.id
    action = query.data
    pending = PENDING.get(chat_id)

    if action == "cancel":
        PENDING.pop(chat_id)
        await query.edit_message_text("Đã huỷ, không ghi gì vào sổ.")
        return

    if pending is None:
        await query.edit_message_text("Phiên chờ đã hết hạn (30 phút). Gửi lại tin nhắn giúp mình nhé.")
        return

    if action == "edit":
        PENDING.pop(chat_id)
        await query.edit_message_text("Ok, gửi lại tin nhắn đã sửa. Mình sẽ bóc lại từ đầu.")
        return

    if action == "commit":
        if STORE is None:
            await query.edit_message_text("Sổ chưa kết nối được.")
            return
        try:
            rows = [p.as_row() for p in pending.items]
            written = STORE.append(rows)
        except Exception as exc:
            log.exception("Lỗi ghi sổ")
            await query.edit_message_text(f"⚠️ Lỗi ghi sổ: {exc}")
            return
        PENDING.pop(chat_id)
        span = f"{written[0]}–{written[-1]}" if len(written) > 1 else str(written[0])
        await query.edit_message_text(
            f"✅ Đã ghi {len(written)} dòng vào sổ (dòng {span}).\nGõ /undo để xoá nếu sai."
        )


# ────────────────────────── wiring ──────────────────────────


BOT_COMMANDS = [
    ("ghi", "Ghi sổ: /ghi p304 tt 1.480.000 chi soho"),
    ("id", "Xem chat_id"),
    ("tail", "10 dòng cuối của sổ"),
    ("undo", "Xoá dòng bot vừa ghi"),
    ("start", "Bắt đầu / hướng dẫn"),
    ("help", "Trợ giúp"),
]


async def _register_commands(application: Application) -> None:
    """Tự đặt menu lệnh mỗi lần khởi động.

    Lý do: menu lệnh đặt qua API có thể bị mất; đặt lại ở đây thì khởi động
    là có, không phải chạy script tay.
    """
    from telegram import BotCommand

    commands = [BotCommand(cmd, desc) for cmd, desc in BOT_COMMANDS]
    scopes = [
        None,  # default (mọi scope)
        {"type": "all_private_chats"},
        {"type": "all_group_chats"},
    ]
    for scope in scopes:
        try:
            await application.bot.set_my_commands(commands, scope=scope)
        except Exception as exc:
            log.warning("Không đặt được menu lệnh (scope=%s): %s", scope, exc)
    log.info("Đã đặt menu lệnh: %s", ", ".join(c for c, _ in BOT_COMMANDS))


async def post_init(application: Application) -> None:
    global STORE
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    # Ghi log ra file để đọc lại được (output PowerShell có thể bị buffer/che).
    try:
        log_path = config.data_dir() / "bot.log"
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
        print(f"[log] {log_path}", flush=True)
    except OSError:
        pass

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        level=logging.INFO,
        handlers=handlers,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    await _register_commands(application)
    try:
        STORE = build_store(HEADER_ROW)
        log.info("Kết nối sổ OK: %s", STORE.info())
    except Exception as exc:
        log.error("Không kết nối được sổ: %s", exc)
        STORE = None


async def on_update_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Group -2: log MỌI update thô để biết Telegram có gửi hay không."""
    chat = update.effective_chat
    msg = update.effective_message
    ents = [(e.type, e.offset, e.length) for e in (getattr(msg, "entities", None) or [])]
    log.info(
        "RAW update: chat=%s type=%s text=%r entities=%s",
        getattr(chat, "id", None),
        getattr(chat, "type", None),
        (getattr(msg, "text", None) or "")[:80],
        ents,
    )


async def log_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler nhóm -1: log MỌI update kèm chat_id, kể cả lệnh không đi qua _guard.

    Nhờ vậy khi setup chỉ cần nhắn bất kỳ tin gì là đọc được chat_id từ log.
    """
    chat = update.effective_chat
    user = update.effective_user
    if chat is not None:
        log.info(
            "chat_id=%s type=%s title=%s user=@%s",
            chat.id,
            chat.type,
            getattr(chat, "title", None) or getattr(chat, "first_name", None),
            getattr(user, "username", None),
        )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Lỗi khi xử lý update", exc_info=context.error)


def build_application() -> Application:
    app = Application.builder().token(config.telegram_token).post_init(post_init).build()
    # group -2: log MỌI update thô (kể cả khi không handler nào khớp)
    app.add_handler(MessageHandler(filters.ALL, on_update_debug), group=-2)
    # group -1: chỉ để ghi log chat_id gọn
    app.add_handler(MessageHandler(filters.ALL, log_chat_id), group=-1)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("ghi", cmd_ghi))
    app.add_handler(CommandHandler("tail", cmd_tail))
    app.add_handler(CommandHandler("undo", cmd_undo))
    app.add_handler(CallbackQueryHandler(on_callback, pattern="^(commit|edit|cancel)$"))
    # Group: bot chỉ phản hồi khi được @mention hoặc reply (tránh spam group).
    # Đặt TRƯỚC handler photo/text chung, vì handler đầu tiên khớp sẽ chặn các sau.
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.CAPTION | filters.PHOTO) & filters.ChatType.GROUPS & ~filters.COMMAND,
            on_group_text,
        )
    )
    # Chat riêng: nhận mọi tin
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def _health_server():
    """Server HTTP tối giản để Render health check không làm service bị coi là chết.

    Chạy trên PORT (Render set sẵn). Không phục vụ gì ngoài / và /healthz.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path in ("/", "/healthz", "/health"):
                body = b"ok"
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, *args):  # bớt spam log
            pass

    port = config.port or 10000
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> None:
    problems = config.problems()
    if problems:
        print("⚠️ Cấu hình chưa đủ:")
        for p in problems:
            print("  -", p)
        print("\nSửa file .env (hoặc biến môi trường) rồi chạy lại.")
        if any("TELEGRAM_BOT_TOKEN" in p for p in problems):
            raise SystemExit(1)

    app = build_application()
    log.info("Bot đang chạy (model %s @ %s)", config.ai_model, config.ai_base_url)
    log.info("Sổ: %s", config.sheet_backend)

    if config.webhook_url:
        # Webhook: chính aiohttp server của PTB phục vụ HTTP trên PORT,
        # nên KHÔNG mở health server riêng (sẽ tranh cổng).
        # Render health check nên trỏ vào /telegram/ hoặc /healthz bên dưới.
        log.info("Chạy webhook tại %s (cổng %s)", config.webhook_url, config.port or 10000)
        app.run_webhook(
            listen="0.0.0.0",
            port=config.port or 10000,
            url_path="telegram",
            webhook_url=f"{config.webhook_url.rstrip('/')}/telegram",
            secret_token=config.webhook_secret or None,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )
        return

    # Polling + health server: hợp cho Render free (process sống lâu).
    # Render free spin down sau 15 phút không có request vào -> cần pinger bên ngoài
    # gọi /healthz mỗi 10 phút để giữ service thức (xem DEPLOY.md).
    if config.enable_health_server or config.port:
        _health_server()
        log.info("Health server trên cổng %s (GET /healthz)", config.port or 10000)
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
