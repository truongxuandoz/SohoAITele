# Dùng bot trong GROUP Telegram

## TL;DR — 3 việc chính

```
/ghi P203, 302, tt đủ 960k, soho     ← GHI sổ
/xem                                  ← XEM thống kê tháng này
/hoi tháng này còn lại bao nhiêu?    ← HỎI về sổ
```

**Đừng dùng `@mention`** — nó không hoạt động khi privacy mode bật.

---

## `/ghi` — Ghi sổ

### Cách 1: một dòng

```
/ghi p304 tt 1.480.000 chi soho
/ghi P203, 302, tt đủ 960k, soho
/ghi P202 tt 6 bò húc, 4 thạch bích, 4 mì 240000 soho
```

### Cách 2: nhiều dòng (ForceReply)

Gõ `/ghi` trống → bot hiện ô nhập → bạn reply vào ô đó và dán cả khối:

```
11/8
p304 tt 990.000
suối 10k chi tm
p102 cọc 500k soho
```

Bước reply là mấu chốt: Telegram coi đó là "reply meant for this bot" nên cho qua privacy mode.

### Ảnh hoá đơn

Gửi **ảnh trực tiếp** vào group, **không cần mention**. Bot đọc ảnh rồi hiện preview.

Có thể kèm caption: `chuyển khoản 960k soho`

Sau khi hiện preview, bấm **✅ Ghi sổ**. Nút sẽ biến mất sau khi ghi để tránh bấm 2 lần.

---

## `/xem` — Thống kê tháng

```
/xem            → tháng này
/xem 8          → tháng 8 (năm nay)
/xem 8/2026     → tháng 8 năm 2026
```

Bot trả về:

```
📊 Tháng 08/2026

Tổng thu : 197.264.672
Tổng chi : 196.586.159
Còn lại  : +678.513
334 bút toán

Theo nhãn
• soho: thu 129.239.672 · chi 118.818.107 (187)
• kim: thu 34.425.000 · chi 47.028.052 (52)
• tm: thu 33.600.000 · chi 30.700.000 (94)

Dòng tiền hiện tại
• 01/08: -650.000
• 02/08: -1.540.000
...
• 31/08: 678.513
```

**Số này tính bằng code, không qua AI** — chính xác tuyệt đối. Đã đối chiếu với
công thức `=SUM(C314:C658)` trong sổ: khớp **0 đồng**.

---

## `/hoi` — Hỏi về sổ

```
/hoi tháng này còn lại bao nhiêu?
/hoi chi nhiều nhất cho việc gì?
/hoi tuần này thu được bao nhiêu?
/hoi soho giữ bao nhiêu tiền?
```

AI đọc dữ liệu sổ thật rồi trả lời. **Không bịa số** — mọi con số lấy từ sổ.

Trong **chat riêng**, chỉ cần gõ câu hỏi, không cần `/hoi`:

```
kiểm tra dòng tiền hiện tại của tháng này
```

Bot tự nhận ra câu hỏi (có `?`, hoặc chứa "kiểm tra", "xem", "bao nhiêu",
"thống kê", "còn lại"...) và trả lời thay vì bóc bút toán.

---

## Bằng chứng: bot nhận gì, không nhận gì

Log thật từ `data/bot.log`:

```
14:07:52  text='/id' entities=[BOT_COMMAND]                     ← LỆNH: NHẬN
14:09:xx  (không có dòng nào)                                    ← @mention: KHÔNG
14:16:04  text='/tail@SohoBoutiqueQNbot'                        ← LỆNH: NHẬN
15:41:05  text='' entities=[]                                    ← ẢNH: NHẬN
16:08:25  (không có dòng nào cho "@Bot kiểm tra dòng tiền...")   ← @mention: KHÔNG
```

Đối chiếu [docs Telegram → Privacy Mode](https://core.telegram.org/bots/features#privacy-mode):

> By default, **all bots** added to groups run in Privacy Mode and only see relevant messages and commands:
> - Commands explicitly meant for them (e.g. `/command@this_bot`)
> - General commands (e.g. `/start`) if the bot was the last bot to send a message to the group
> - Inline messages sent via the bot
> - **Replies to any messages implicitly or explicitly meant for this bot**

> All bots will also receive, **regardless of privacy mode**:
> - All service messages
> - **All messages from private chats**
> - All messages from channels where they are a member

Kết luận: tin `@BotUsername nội dung` là **tin thường**, không phải lệnh cũng
không phải reply → bị lọc. **Chat riêng không bị ảnh hưởng** vì privacy mode
chỉ áp dụng cho group.

---

## Năm cách dùng bot trong group

### Cách 1 — Lệnh (khuyến nghị)

`/ghi`, `/xem`, `/hoi`, `/tail`, `/undo`, `/id`

Luôn hoạt động, không cần đổi cài đặt, không đọc trộm tin của người khác.

### Cách 2 — Gửi ảnh

Ảnh không thể chứa mention text, nên bot **luôn nhận ảnh** trong group
(không cần @mention). Chỉ cần group đã có trong `ALLOWED_CHAT_ID`.

### Cách 3 — Reply vào tin của bot

Bot gửi preview → bạn **reply** vào chính tin đó:

```
↳ p301 coc 20/8 500k
```

### Cách 4 — Cho bot làm ADMIN (mạnh nhất)

Docs Telegram:

> Privacy mode is enabled by default for all bots, **except bots that were added
> to a group as admins** (bot admins always receive **all messages**).

**Cách làm:** group → tên group → **Soho Ai** → **Promote to admin** (chỉ cần
quyền gửi tin) → Save.

Sau đó `@mention` và dán nhiều dòng trực tiếp đều chạy.

> ⚠️ Bot sẽ đọc được mọi tin của thành viên. Chỉ làm khi group riêng.

### Cách 5 — Tắt privacy qua BotFather

@BotFather → `/setprivacy` → chọn bot → **Disable** → **gỡ bot khỏi group rồi add lại**.

Bước gỡ/thêm lại là **bắt buộc** — privacy mode chỉ đọc lúc bot được thêm vào group.

---

## Menu lệnh `/` trống

Bot tự đặt menu mỗi lần khởi động:

```
INFO  Đã đặt menu lệnh: ghi, xem, hoi, id, tail, undo, start, help
```

Nếu vẫn trống: **Telegram cache ở client**. Đóng hẳn app (không chỉ thu nhỏ) rồi mở lại.

> Không chờ menu — gõ tay `/ghi`, `/xem`, `/hoi` là được ngay.

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
| Chat riêng OK, group im | Privacy mode lọc tin thường | Dùng `/ghi`, `/xem`, `/hoi` |
| `@Bot nội dung` không phản hồi | Tin thường bị privacy lọc | Đổi sang `/ghi nội dung` |
| Ảnh trong group không xử lý | Code cũ chặn trước khi kiểm tra photo | Đã sửa — restart bot |
| `/xem` báo "chưa có bút toán" | Tháng đó chưa có dòng nào có ngày | Thử `/xem 8/2026` |
| `/hoi` timeout | Prompt quá lớn | Đã sửa — chỉ gửi tóm tắt |
| Bấm Ghi sổ báo "hết hạn" | Pending cũ / bấm 2 lần | Đã sửa — xem INCIDENTS.md |
| Menu `/` trống | Client cache | Đóng hẳn app mở lại |
| `⛔ Chưa được cấp quyền` | Group chưa có trong `ALLOWED_CHAT_ID` | `/id` → thêm số âm → restart |
| Bot trả lời 2 lần | 2 instance cùng chạy | `Get-Process python` → kill bản cũ |
| Bot im hoàn toàn | Bot tắt | Xem `data/bot.log` |

### Debug nhanh

Bot ghi **mọi** update vào `data/bot.log`:

```powershell
Get-Content data\bot.log -Tail 30
```

- Không thấy `RAW update` → Telegram không gửi tới bot (privacy mode, hoặc bot không ở trong group)
- Có `RAW update` nhưng không phản hồi → tìm `HANDLER ...` và `ERROR`
- Không có `RAW update` cho `/ghi` → bot chạy code cũ, cần restart

---

## Ghi chú kỹ thuật

### `/ghi` — hai nhánh

```python
text = " ".join(context.args or []).strip()
if text:
    await _handle_text(update, context, text)   # một dòng
    return
await update.effective_message.reply_text(
    "Gửi nội dung bút toán...",
    reply_markup=ForceReply(selective=True),    # xin nội dung nhiều dòng
)
```

`context.args` là **list** các từ sau lệnh → phải `" ".join()`.
`ForceReply(selective=True)` khiến chỉ người gõ lệnh thấy ô nhập.

### `/xem` — vì sao chính xác

Đọc cột Ngày tháng phải xử lý 3 đặc điểm của sổ thật:

1. **Ngày là serial number** — `UNFORMATTED_VALUE` trả `46235`, không phải `"1/8"`.
   Quy đổi: `date(1899,12,30) + timedelta(days=46235)`.
2. **Cột A chỉ điền ở dòng đầu mỗi ngày** — dòng sau để trống, phải *fill down*.
3. **Có dòng `Tổng` chen giữa vùng dữ liệu** — phải loại, và **cắt fill-down** tại đó.
   Nhưng cẩn thận: `"P 101 tt còn lại"` là bút toán thật, chỉ coi là dòng tổng
   khi ô nội dung **bắt đầu** bằng từ khoá tổng.

### `/hoi` — vì sao nhanh

Không gửi toàn bộ 656 dòng cho AI (prompt ~50KB → timeout 60s). Thay vào đó:

- Tính sẵn thống kê theo tháng/nhãn bằng code
- Gửi tóm tắt (~5KB) + 40 dòng gần nhất

Kết quả: 7 giây thay vì timeout.

### `on_group_text` — thứ tự kiểm tra quan trọng

```python
if message.photo:              # ẢNH trước — không cần mention
    await on_photo(update, context)
    return
if not (mentioned or replied_to_me):
    return
```

Nếu đảo thứ tự, ảnh sẽ bị chặn vì ảnh không thể chứa mention.

### Test

`tests/test_ghi_command.py`, `test_ghi_force_reply.py`, `test_photo_group.py`,
`test_pending_group.py`, `test_report.py`, `test_group.py`
