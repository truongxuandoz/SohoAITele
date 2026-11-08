# Dùng bot trong GROUP Telegram

## TL;DR

Trong group, gõ:

```
/ghi
```

Bot hiện ô nhập (ForceReply) → bạn dán nội dung (nhiều dòng cũng được) → bot bóc bút toán.

Hoặc gõ tắt một dòng:

```
/ghi p304 tt 1.480.000 chi soho
```

**Đừng dùng `@mention`** — nó không hoạt động (xem bằng chứng bên dưới).

---

## Bằng chứng: bot nhận gì, không nhận gì

Log thật từ `data/bot.log`:

```
14:07:52  RAW update: text='/id' entities=[BOT_COMMAND]        ← LỆNH: NHẬN
14:09:xx  (không có dòng nào)                                   ← @mention: KHÔNG NHẬN
14:10:xx  (không có dòng nào)                                   ← @mention: KHÔNG NHẬN
14:11:20  RAW update: type=private text='hi'                    ← chat riêng: OK
14:16:04  RAW update: text='/tail@SohoBoutiqueQNbot' entities=[BOT_COMMAND]  ← LỆNH: NHẬN
```

Đối chiếu với [docs Telegram → Privacy Mode](https://core.telegram.org/bots/features#privacy-mode):

> By default, **all bots** added to groups run in Privacy Mode and only see relevant messages and commands:
> - Commands explicitly meant for them (e.g. `/command@this_bot`)
> - General commands (e.g. `/start`) if the bot was the last bot to send a message to the group
> - Inline messages sent via the bot
> - **Replies to any messages implicitly or explicitly meant for this bot**

> All bots will also receive, **regardless of privacy mode**:
> - All service messages
> - **All messages from private chats**
> - All messages from channels where they are a member

Kết luận: một tin `@BotUsername nội dung` là **tin thường**, không phải lệnh cũng không phải reply → bị lọc.

**Vì sao chat riêng mượt:** privacy mode chỉ áp dụng cho group.

---

## Luồng `/ghi` + ForceReply (khuyến nghị)

Đây là cách docs Telegram khuyến nghị:

> In most cases, using the **force reply** option for the bot's messages should be more than enough.

### Cách hoạt động

```
Bạn:  /ghi
Bot:  "Gửi nội dung bút toán — dán nhiều dòng cũng được.
       11/8
       p304 tt 990.000
       suối 10k chi tm"          ← ô nhập (ForceReply)
Bạn:  (reply vào ô đó, dán cả khối)
Bot:  preview + nút ✅ Ghi sổ
```

Bước 3 là **reply vào tin của bot** → privacy mode cho qua.

### Vì sao tốt hơn `@mention`

| | `/ghi` + ForceReply | `@mention` |
|---|---|---|
| Hoạt động khi privacy bật | ✅ | ❌ |
| Dán nhiều dòng | ✅ | ❌ |
| Không đọc tin người khác | ✅ | ✅ |
| Cần đổi cài đặt | Không | Phải tắt privacy |

### Gõ tắt một dòng

```
/ghi p304 tt 1.480.000 chi soho
```
Không cần ForceReply, xử lý ngay.

---

## Ba cách dùng trong group

### Cách 1 — `/ghi` (khuyến nghị)

```
/ghi
```
rồi reply với nội dung. Hoặc `/ghi nội dung...` cho một dòng.

- Luôn hoạt động, không cần đổi cài đặt
- Không đọc trộm tin của người khác trong group

### Cách 2 — Reply vào tin của bot

Bot gửi preview → bạn **reply** vào chính tin đó:
```
↳ p301 coc 20/8 500k
```
Telegram coi reply là "meant for this bot" nên cho qua.

### Cách 3 — Cho bot làm ADMIN (mạnh nhất)

Docs Telegram dòng 950:

> Privacy mode is enabled by default for all bots, **except bots that were added to a group as admins** (bot admins always receive **all messages**).

**Cách làm:** group → tên group → **Soho Ai** → **Promote to admin** (chỉ cần quyền gửi tin) → Save.

Sau đó bot nhận **mọi** tin trong group: `@mention`, dán nhiều dòng trực tiếp, gửi ảnh — tất cả đều chạy như chat riêng.

> ⚠️ Bot sẽ đọc được mọi tin của thành viên. Chỉ làm khi group riêng.

### Cách 4 — Tắt privacy mode qua BotFather

@BotFather → `/setprivacy` → chọn bot → **Disable** → **gỡ bot khỏi group rồi add lại**.

Bước gỡ/thêm lại là **bắt buộc** — privacy mode chỉ đọc lúc bot được thêm vào group.

---

## Menu lệnh `/` trống — nguyên nhân và cách sửa

Menu lệnh **không tự có**. Phải gọi `setMyCommands`. Bot giờ tự làm mỗi lần khởi động:

```python
async def _register_commands(application):
    commands = [BotCommand(cmd, desc) for cmd, desc in BOT_COMMANDS]
    for scope in (None, {"type": "all_private_chats"}, {"type": "all_group_chats"}):
        await application.bot.set_my_commands(commands, scope=scope)
```

Log khi khởi động:
```
INFO  Đã đặt menu lệnh: ghi, id, tail, undo, start, help
```

Kiểm tra qua API:
```powershell
curl.exe -s "https://api.telegram.org/bot<TOKEN>/getMyCommands"
```

Nếu menu vẫn trống: **Telegram cache ở client**. Đóng hẳn app (không chỉ thu nhỏ) rồi mở lại.

> Không chờ menu — gõ tay `/ghi` là được ngay.

---

## Lấy `chat_id` của group

```
/id
```
Bot trả:
```
chat_id: -5591223295
type: group
title: Soho AI Thu Chi
```

Group luôn là **số âm**. Thêm vào `.env`:
```
ALLOWED_CHAT_ID=6241137644,-5591223295
```

---

## Xử lý sự cố

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| Chat riêng OK, group im | Privacy mode lọc tin thường | Dùng `/ghi` |
| `@BotUsername nội dung` không phản hồi | Tin thường bị privacy lọc | Đổi sang `/ghi` |
| Menu `/` trống | Chưa set commands / client cache | Bot tự set khi khởi động; đóng hẳn app mở lại |
| `/ghi` không thấy trong menu | Bot chưa restart sau update | Khởi động lại bot, xem log `Đã đặt menu lệnh` |
| `⛔ Chat này chưa được cấp quyền` | Group chưa có trong `ALLOWED_CHAT_ID` | `/id` → thêm số âm → restart |
| Bot trả lời 2 lần | 2 instance cùng chạy | `Get-Process python` → kill bản cũ |
| Bot im hoàn toàn | Bot tắt | Xem `data/bot.log` |

### Debug nhanh

Bot ghi **mọi** update vào `data/bot.log`:

```powershell
Get-Content data\bot.log -Tail 30
```

- Không thấy dòng `RAW update` → Telegram không gửi tới bot (privacy mode, hoặc bot không ở trong group)
- Có `RAW update` nhưng không phản hồi → tìm dòng `HANDLER ...` và `ERROR`
- Không có `RAW update` cho `/ghi` → bot đang chạy code cũ, cần restart

---

## Ghi chú kỹ thuật

`/ghi` có hai nhánh:

```python
async def cmd_ghi(update, context):
    text = " ".join(context.args or []).strip()
    if text:
        await _handle_text(update, context, text)   # một dòng
        return
    await update.effective_message.reply_text(
        "Gửi nội dung bút toán...",
        reply_markup=ForceReply(selective=True),    # xin nội dung nhiều dòng
    )
```

`context.args` là **list** các từ sau lệnh → phải `" ".join()` để dựng lại câu có dấu cách.

`ForceReply(selective=True)` khiến **chỉ người gõ lệnh** thấy ô nhập — người khác trong group không bị làm phiền.

`on_group_text()` xử lý nhánh reply: kiểm tra `reply_to_message.from_user.id == bot.id` → nếu đúng thì xử lý.

Test: `tests/test_ghi_force_reply.py` (4) + `tests/test_ghi_command.py` (5) + `tests/test_group.py` (9).


