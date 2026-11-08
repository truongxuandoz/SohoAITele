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
from .dates import ensure_date_present
from .heartbeat import Heartbeat
from .money import format_money
from .pending import Pending, PendingStore
from .report import (
    answer_question,
    format_month_summary,
    looks_like_question,
    month_summary,
)
from .sheets import build_store

log = logging.getLogger(__name__)

PENDING = PendingStore(config.data_dir() / "pending.json")
STORE = None  # khởi tạo trong post_init, tránh crash lúc import
HEADER_ROW = 2
# Dashboard đọc file này để biết bot còn sống và đang làm gì
HB = Heartbeat(config.data_dir() / "status.json")

HELP_TEXT = """<b>SoHo AI</b> — ghi sổ & tra cứu bằng AI

<b>GHI SỔ</b>
Chat riêng — gõ tự do:
<code>p304 tt 1.480.000 chi soho</code>
<code>hôm nay chi 159k cước hotline</code>

Group — dùng lệnh:
<code>/ghi P203, 302, tt đủ 960k, soho</code>

Nhiều dòng một lúc — dán cả khối:
<code>11/8
p304 tt 990.000
suối 10k</code>

<b>XEM SỔ</b>
/xem – thống kê thu chi tháng này
/xem 8 – tháng 8
/xem 8/2026 – tháng 8 năm 2026

<b>HỎI VỀ SỔ</b>
/hoi tháng này còn lại bao nhiêu?
/hoi chi nhiều nhất cho việc gì?
/hoi tuần này thu được bao nhiêu?

Trong chat riêng chỉ cần gõ câu hỏi, không cần /hoi.

<b>KHÁC</b>
/tail – 10 dòng cuối của sổ
/undo – xoá dòng bot vừa ghi
/id – xem chat_id

Gửi <b>ảnh</b> hoá đơn / sổ tay cũng được — bot đọc rồi bóc."""


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


def _preview_text(items: list[Item], note: str, date_notes: list[str] | None = None) -> str:
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
    if date_notes:
        lines.append("")
        for dn in date_notes:
            lines.append(f"<i>{_esc(dn)}</i>")
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


async def cmd_xem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Thống kê thu/chi tháng. Cú pháp: /xem [tháng] [năm]"""
    if not await _guard(update):
        return
    if STORE is None:
        await update.effective_message.reply_text("Sổ chưa kết nối được.")
        return

    args = list(context.args or [])
    month = year = None
    try:
        if args:
            # Nhận "8", "08", "8/2026", "8 2026"
            part = args[0]
            if "/" in part:
                m, y = part.split("/", 1)
                month, year = int(m), int(y)
            else:
                month = int(part)
            if len(args) > 1 and not year:
                year = int(args[1])
    except (ValueError, IndexError):
        await update.effective_message.reply_text(
            "Cú pháp: <code>/xem</code> (tháng này)\n"
            "<code>/xem 8</code> (tháng 8)\n"
            "<code>/xem 8/2026</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        summary = month_summary(STORE, year=year, month=month)
    except Exception as exc:
        log.exception("Lỗi thống kê")
        HB.bump("errors")
        HB.event("error", f"xem: {exc}")
        await update.effective_message.reply_text(f"⚠️ Không đọc được sổ: {exc}")
        return

    HB.event("report", f"xem tháng {summary['month']}/{summary['year']}")
    await update.effective_message.reply_text(
        format_month_summary(summary), parse_mode=ParseMode.HTML
    )


async def cmd_hoi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Hỏi tự do về sổ. Cú pháp: /hoi <câu hỏi>"""
    if not await _guard(update):
        return
    if STORE is None:
        await update.effective_message.reply_text("Sổ chưa kết nối được.")
        return

    question = " ".join(context.args or []).strip()
    if not question:
        await update.effective_message.reply_text(
            "Cú pháp: <code>/hoi tháng này còn lại bao nhiêu?</code>\n"
            "Hoặc: <code>/hoi chi nhiều nhất cho việc gì?</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    HB.bump("ai_calls")
    try:
        answer = answer_question(STORE, question)
    except Exception as exc:
        log.exception("Lỗi trả lời câu hỏi")
        HB.bump("errors")
        HB.event("error", f"hoi: {exc}")
        await update.effective_message.reply_text(f"⚠️ Không trả lời được: {exc}")
        return

    HB.event("answer", question[:60])
    await update.effective_message.reply_text(answer)


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


async def _send_preview(
    message,
    items: list[Item],
    note: str,
    chat_id: int,
    date_notes: list[str] | None = None,
) -> None:
    """Gửi preview rồi lưu pending gắn với message_id của chính tin preview.

    Phải lưu theo message_id vì trong group có nhiều người: nếu chỉ khoá theo
    chat_id, preview của người này ghi đè người kia và bấm nút sẽ báo hết hạn.
    """
    sent = await message.reply_text(
        _preview_text(items, note, date_notes),
        reply_markup=_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    msg_id = getattr(sent, "message_id", None)
    PENDING.put(chat_id, Pending(items=items, note=note), message_id=msg_id)


async def _handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if not await _guard(update):
        return
    message = update.effective_message
    chat_id = update.effective_chat.id

    chat = update.effective_chat
    where = getattr(chat, "title", None) or getattr(chat, "first_name", None) or str(chat_id)
    HB.bump("messages_received")
    HB.event("message", f"{where}: {text[:70]}")

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
        HB.bump("ai_calls")
        items, note = parse_message(
            text, context_rows=context_rows, headers=headers, today=_today_date()
        )
    except Exception as exc:
        log.exception("Lỗi AI")
        HB.bump("errors")
        HB.event("error", f"AI: {exc}")
        HB.ping(last_error=f"AI: {exc}")
        await message.reply_text(f"⚠️ Lỗi gọi AI: {exc}")
        return

    if not items:
        # Không thấy số tiền: có thể là CÂU HỎI chứ không phải bút toán.
        # Ví dụ "kiểm tra dòng tiền tháng này" -> trả lời, đừng báo lỗi.
        if looks_like_question(text):
            try:
                HB.bump("ai_calls")
                answer = answer_question(STORE, text)
            except Exception as exc:
                log.exception("Lỗi trả lời câu hỏi")
                HB.bump("errors")
                HB.event("error", f"hoi: {exc}")
                await message.reply_text(f"⚠️ Không trả lời được: {exc}")
                return
            HB.event("answer", text[:60])
            await message.reply_text(answer)
            return

        HB.event("empty", f"không có số tiền: {text[:50]}")
        await message.reply_text(
            "Mình chưa thấy số tiền nào trong tin nhắn.\n"
            "Thử lại kiểu: <code>p304 tt 1.480.000 chi soho</code>\n"
            "Hoặc hỏi: <code>/hoi tháng này còn lại bao nhiêu?</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(items) > config.max_items:
        await message.reply_text(
            f"⚠️ Tối đa {config.max_items} dòng mỗi lần. Tin nhắn này có {len(items)} dòng."
        )
        return

    # Kiểm tra NGƯỢC ngày: ngày user nói có thật trong sổ chưa?
    # Nếu chưa -> phải ghi ngày vào cột A, không để trống (trống = sai ngày).
    date_notes: list[str] = []
    try:
        date_notes = ensure_date_present(items, STORE, text)
    except Exception as exc:  # pragma: no cover - không để lỗi này chặn ghi sổ
        log.warning("Không kiểm tra được ngày: %s", exc)

    HB.bump("entries_parsed", len(items))
    HB.event("parsed", f"{len(items)} bút toán từ: {text[:50]}")
    HB.ping(last_message=text[:100])
    await _send_preview(message, items, note, chat_id, date_notes=date_notes)


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

    # Chỉ xử lý khi bot thực sự được gọi tên.
    # NHƯNG: ảnh gửi vào group gần như luôn là ảnh cho bot (hoá đơn, sổ tay),
    # và ảnh không thể chứa mention dạng text -> nếu bắt mention thì ảnh
    # không bao giờ được xử lý. Nên với PHOTO, cho qua luôn.
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

    if message.photo:
        # Ảnh: không cần mention. Chỉ cần bot được phép ở chat này
        # (kiểm tra trong on_photo qua _guard).
        await on_photo(update, context)
        return

    if not (mentioned or replied_to_me):
        return  # không gọi bot -> im lặng, không spam group

    text = message.text or message.caption or ""
    if me_username:
        text = text.replace(f"@{context.bot.username}", " ")
    text = " ".join(text.split()).strip()

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


def _guess_mime(raw: bytes, reported: str | None = None) -> str:
    """Xác định mime thật của ảnh từ magic bytes.

    Không tin hoàn toàn mime Telegram báo: có trường hợp trả về
    application/octet-stream, khiến model từ chối ảnh.
    """
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if reported and reported.startswith("image/"):
        return reported
    return "image/jpeg"


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ảnh (sổ tay, hoá đơn) -> gửi base64 cho model vision."""
    if not await _guard(update):
        return
    message = update.effective_message
    chat_id = update.effective_chat.id
    caption = message.caption or ""

    if not message.photo:
        await message.reply_text("Mình chỉ đọc được ảnh chụp (photo), không đọc được file.")
        return

    # photo[-1] là kích thước LỚN NHẤT Telegram lưu. Ảnh nén của Telegram
    # luôn là JPEG, nên mime cố định "image/jpeg" ở đây là đúng.
    photo = message.photo[-1]
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    HB.bump("messages_received")
    HB.event("photo", f"{getattr(message, 'caption', None) or 'ảnh'} ({photo.width}x{photo.height})")

    try:
        file = await context.bot.get_file(photo.file_id)
        raw = bytes(await file.download_as_bytearray())
    except Exception as exc:
        log.exception("Không tải được ảnh")
        HB.bump("errors")
        HB.event("error", f"tải ảnh: {exc}")
        await message.reply_text(f"⚠️ Không tải được ảnh: {exc}")
        return

    if not raw:
        await message.reply_text("⚠️ Ảnh rỗng, gửi lại giúp mình.")
        return

    log.info("Đọc ảnh %s bytes (mime %s)", len(raw), getattr(file, "mime_type", "?"))
    HB.bump("ai_calls")
    try:
        # Dùng đúng mime Telegram báo; nếu không có thì đoán theo magic bytes.
        mime = _guess_mime(raw, getattr(file, "mime_type", None))
        items, note = parse_image(raw, mime=mime, caption=caption)
    except Exception as exc:
        log.exception("Lỗi AI vision")
        HB.bump("errors")
        HB.event("error", f"AI vision: {exc}")
        HB.ping(last_error=f"vision: {exc}")
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
    await _send_preview(message, items, note, chat_id)


async def _safe_edit(query, text: str, **kwargs) -> None:
    """edit_message_text không được làm sập handler.

    Telegram trả BadRequest 'Message is not modified' khi nội dung mới giống
    hệt nội dung cũ — xảy ra khi user bấm nút 2 lần. Đó không phải lỗi thật,
    chỉ cần bỏ qua.
    """
    from telegram.error import BadRequest

    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            return
        raise


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_allowed(update):
        await _safe_edit(query, "⛔ Không có quyền.")
        return

    chat_id = update.effective_chat.id
    action = query.data
    # message_id của chính tin preview đang có nút -> khoá đúng pending đó.
    # Group có nhiều người: khoá theo chat_id trần sẽ ghi đè lẫn nhau.
    preview_msg_id = getattr(getattr(query, "message", None), "message_id", None)
    pending = PENDING.get(chat_id, preview_msg_id)

    if action == "cancel":
        PENDING.pop(chat_id, preview_msg_id)
        await _safe_edit(query, "Đã huỷ, không ghi gì vào sổ.", reply_markup=None)
        return

    if pending is None:
        # Không nói "hết hạn" một cách chung chung: rất có thể lần ghi trước
        # đã thành công rồi (nút vẫn còn trên tin nhắn cũ). Nói rõ để user
        # không tưởng mất dữ liệu và bấm lại nhiều lần.
        await _safe_edit(
            query,
            "Lần ghi này đã xử lý xong rồi (hoặc đã quá 30 phút).\n"
            "Không có gì bị mất.\n\n"
            "• Muốn xoá dòng vừa ghi → gõ /undo\n"
            "• Muốn ghi bút toán mới → gửi /ghi kèm nội dung",
            reply_markup=None,
        )
        return

    if action == "edit":
        PENDING.pop(chat_id, preview_msg_id)
        await _safe_edit(
            query, "Ok, gửi lại tin nhắn đã sửa. Mình sẽ bóc lại từ đầu.", reply_markup=None
        )
        return

    if action == "commit":
        if STORE is None:
            await _safe_edit(query, "Sổ chưa kết nối được.")
            return

        # Lấy pending ra TRƯỚC khi ghi: nếu user bấm 2 lần, lần thứ 2 sẽ
        # không thấy pending nên không ghi trùng.
        claimed = PENDING.pop(chat_id, preview_msg_id)
        if claimed is None:
            await _safe_edit(
                query, "Bút toán này đã được ghi rồi. Gõ /undo nếu muốn xoá.", reply_markup=None
            )
            return
        pending = claimed

        try:
            rows = [p.as_row() for p in pending.items]
            written = STORE.append(rows)
        except Exception as exc:
            log.exception("Lỗi ghi sổ")
            # Ghi lỗi -> trả pending lại để user bấm lại được, không mất công dán.
            PENDING.put(chat_id, pending, message_id=preview_msg_id)
            HB.bump("errors")
            HB.event("error", f"ghi sổ: {exc}")
            HB.ping(last_error=f"ghi sổ: {exc}")
            await _safe_edit(query, f"⚠️ Lỗi ghi sổ: {exc}\nBấm lại nút để thử lại.")
            return

        span = f"{written[0]}–{written[-1]}" if len(written) > 1 else str(written[0])
        HB.bump("entries_written", len(written))
        HB.event("written", f"{len(written)} dòng → dòng {span}")
        HB.ping()
        # reply_markup=None: bỏ nút sau khi ghi xong, tránh bấm lại lần 2.
        await _safe_edit(
            query,
            f"✅ Đã ghi {len(written)} dòng vào sổ (dòng {span}).\nGõ /undo để xoá nếu sai.",
            reply_markup=None,
        )


# ────────────────────────── wiring ──────────────────────────


BOT_COMMANDS = [
    ("ghi", "Ghi sổ: /ghi p304 tt 1.480.000 chi soho"),
    ("xem", "Thống kê thu chi tháng: /xem [tháng]"),
    ("hoi", "Hỏi về sổ: /hoi tháng này còn bao nhiêu?"),
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


async def _heartbeat_loop(application: Application) -> None:
    """Ping định kỳ 30s để dashboard biết bot còn sống (kể cả khi không có tin)."""
    import asyncio
    import contextlib

    while True:
        with contextlib.suppress(Exception):
            HB.ping()
        await asyncio.sleep(30)


async def post_init(application: Application) -> None:
    global STORE
    import asyncio

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
        HB.sheet_info = STORE.info()
    except Exception as exc:
        log.error("Không kết nối được sổ: %s", exc)
        HB.bump("errors")
        HB.event("error", f"kết nối sổ: {exc}")
        HB.last_error = f"kết nối sổ: {exc}"
        STORE = None

    HB.bot_username = getattr(application.bot, "username", None)
    HB.event("started", f"pid {HB.pid}")
    HB.ping()

    # Task nền: ping đều đặn để dashboard phân biệt "im vì không ai nhắn"
    # với "chết". Không dùng JobQueue để tránh phụ thuộc extra package.
    task = asyncio.create_task(_heartbeat_loop(application))
    application.bot_data["_hb_task"] = task


async def on_update_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Group -2: log MỌI update thô để biết Telegram có gửi hay không."""
    chat = update.effective_chat
    msg = update.effective_message
    ents = [(e.type, e.offset, e.length) for e in (getattr(msg, "entities", None) or [])]
    HB.ping()  # có update = bot còn sống
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
    HB.bump("errors")
    HB.event("error", f"{type(context.error).__name__}: {context.error}")
    HB.ping(last_error=f"{type(context.error).__name__}: {context.error}")


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
    app.add_handler(CommandHandler("xem", cmd_xem))
    app.add_handler(CommandHandler("hoi", cmd_hoi))
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
