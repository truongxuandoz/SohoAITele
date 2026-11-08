# Sự cố đã gặp & cách phòng tránh

Ghi lại các lỗi thật đã xảy ra khi đưa bot vào sổ thật, để không lặp lại.

---

## 0. "Phiên chờ đã hết hạn" ngay sau khi hiện preview (GROUP)

### Triệu chứng
Bấm nút **Ghi sổ** trong group → bot trả *"Phiên chờ đã hết hạn (30 phút). Gửi lại tin nhắn giúp mình nhé."* — dù vừa gửi `/ghi` vài giây trước.

### Dữ liệu có mất không?
**KHÔNG.** Log chứng minh cả 3 bút toán đều ghi thành công:

```
14:59:34  message: p304 tt 500000 thu tk soho
15:00:41  written: 1 dòng → dòng 664        ← ghi THẬT
15:00:50  message: p304 tt 500000 thu tk soho
15:01:02  written: 1 dòng → dòng 665        ← ghi THẬT
15:01:47  message: p203 tt 100000 thu tk kim
15:02:02  written: 1 dòng → dòng 666        ← ghi THẬT
15:02:04  error: Message is not modified     ← chỉ là bấm lại nút cũ
```

### Ba nguyên nhân thật

**1. Khoá pending theo `chat_id` trần — sai trong group**

Group có nhiều người. Cả hai gửi `/ghi` → cái sau **ghi đè** cái trước trong
`pending.json`. Bấm nút trên preview cũ → không tìm thấy → "hết hạn".

```
Trước: {"-5591223295": {...}}          ← 1 khoá cho cả group
Sau:   {"-5591223295:1001": {...},     ← mỗi preview 1 khoá
        "-5591223295:1002": {...}}
```

**2. Bấm nút 2 lần → `BadRequest: Message is not modified`**

Lần 1 ghi xong, nút vẫn còn trên tin nhắn. Lần 2 Telegram từ chối vì nội dung
không đổi → exception làm sập handler.

Sửa: bọc trong `_safe_edit()` để bỏ qua lỗi này, và `reply_markup=None` sau khi
ghi xong để bỏ nút.

**3. Message "hết hạn" gây hoang mang**

User tưởng mất dữ liệu nên bấm lại nhiều lần.

Sửa: nói rõ *"Lần ghi này đã xử lý xong rồi... Không có gì bị mất"* + gợi ý `/undo`.

### Thêm: chống ghi trùng

`PENDING.pop()` giờ chạy **trước** khi ghi sổ. Bấm 2 lần → lần 2 không thấy
pending → không ghi trùng. Trước đây `pop()` sau khi ghi nên có cửa sổ double-write.

### Thêm: pending trả lại khi lỗi

Ghi sổ lỗi (Sheets API 500) → pending được `put()` lại để user bấm thử lại,
không phải dán lại tin nhắn.

### Regression test
`tests/test_pending_group.py` (10 test): 2 người cùng group không ghi đè nhau,
`pop()` chỉ xoá đúng preview được bấm, bấm 2 lần không ghi trùng,
`Message is not modified` được bỏ qua, nút bị bỏ sau khi ghi, lỗi append trả lại
pending, đọc lại file khi process khác ghi, tương thích khoá cũ.

---

## 0b. Ảnh trong GROUP không được xử lý ("nhắn riêng thì được")

### Triệu chứng
Gửi ảnh hoá đơn chuyển khoản vào group → bot **im lặng hoàn toàn**.
Gửi cùng ảnh vào chat riêng → bot đọc và bóc bình thường.

### Chẩn đoán
Log cho thấy ảnh **đã tới bot** nhưng không handler nào xử lý:

```
15:41:05  RAW update: chat=-5591223295 type=group text='' entities=[]
15:41:33  RAW update: chat=-5591223295 type=group text='' entities=[]
```

`text=''` và `entities=[]` là dấu hiệu của **ảnh** (photo không có text).
Không có dòng `HANDLER` nào sau đó, và không có lỗi.

### Nguyên nhân
`on_group_text` kiểm tra **@mention TRƯỚC** khi kiểm tra photo:

```python
# CODE SAI
if not (mentioned or replied_to_me):
    return                      # ← ảnh bị chặn ở đây
...
if message.photo:
    await on_photo(...)
```

Ảnh **không thể chứa mention dạng text** — entities luôn rỗng. Nên điều kiện
`mentioned` luôn False → `return` → ảnh không bao giờ được xử lý.

Chat riêng không qua `on_group_text` mà qua `on_photo` trực tiếp → chạy được.
Đó là lý do "nhắn riêng thì được, group thì không".

### Sửa
Đưa kiểm tra photo lên **trước** điều kiện mention:

```python
# CODE ĐÚNG
if message.photo:
    await on_photo(update, context)   # ảnh không cần mention
    return

if not (mentioned or replied_to_me):
    return
```

`on_photo` vẫn tự gọi `_guard()` nên group lạ vẫn bị chặn.

### Sửa thêm: mime thật của ảnh
Code cũ hardcode `mime="image/jpeg"`. Thêm `_guess_mime()` đọc magic bytes:

| Magic bytes | mime |
|---|---|
| `\x89PNG\r\n\x1a\n` | `image/png` |
| `\xff\xd8\xff` | `image/jpeg` |
| `RIFF....WEBP` | `image/webp` |
| `GIF87a` / `GIF89a` | `image/gif` |

Không tin hoàn toàn mime Telegram báo — có trường hợp trả `application/octet-stream`.

### Kiểm chứng model CÓ vision
Trước khi sửa code, đã test trực tiếp API với ảnh hoá đơn thật:

```
AI note:
Bóc được 1 bút toán:
  1. LE NGUYEN DUY DUONG chuyen tien den KH HO KINH DOANH SOHO BOUTIQUE
     · ngày 13/08/2026 · THU 960.000 · [soho]
Nhan ra 960.000: CO
```

Nghĩa là **model không phải nguyên nhân** — lỗi hoàn toàn ở code bot.

### Regression test
`tests/test_photo_group.py` (10 test): ảnh group không mention vẫn xử lý, ảnh có
caption, text không mention vẫn im lặng, chat riêng vẫn chạy, đoán mime cho
PNG/JPEG/WebP/GIF/octet-stream.

---

## 1. `PendingStore` crash trên filesystem read-only

**Triệu chứng (Vercel/Render):**
```
PermissionError: [Errno 13] Access is denied
```
Crash ngay khi `import soho.bot`, app không boot được.

**Nguyên nhân:** `PendingStore.__init__` gọi `mkdir()` ở module level.

**Đã sửa:** bắt `OSError`, fallback `/tmp`, chạy tiếp trong RAM. Test: `tests/test_cloud.py::test_pending_store_survives_readonly_dir`.

---

## 2. Python 3.14 + python-telegram-bot 21.6

**Triệu chứng:**
```
RuntimeError: There is no current event loop in thread 'MainThread'.
```

**Nguyên nhân:** Python 3.14 bỏ `asyncio.get_event_loop()` ngầm định; PTB 21.6 vẫn dựa vào nó.

**Đã sửa:** pin `python-telegram-bot==22.8` trong `requirements.txt`.

---

## 3. Gateway hermesgate luôn trả SSE

**Triệu chứng:**
```
requests.exceptions.JSONDecodeError: Expecting value: line 1 column 1
```

**Nguyên nhân:** gateway trả `text/event-stream` **kể cả khi không set `stream: true`**. Client gọi `resp.json()` sẽ fail.

**Đã sửa:** `_read_sse()` ghép `delta.content`; có retry 3 lần vì gateway hay timeout 60s.

---

## 4. Ghi sổ sai chỗ — append vào giữa khối Tổng ⚠️ NGHIÊM TRỌNG

**Triệu chứng:** bot sẽ ghi dòng mới vào **R680**, sau khối đối soát tiền mặt.

**Nguyên nhân:** sổ thật **không phải bảng phẳng**:
```
R3..R663   dữ liệu
R664..R670 trống (ngăn cách)
R671       Tổng   =SUM(C314:C658)
R672       Còn lại =C671-D671
R673..R679 ghi chú đối soát tiền mặt
```

Logic cũ tìm "dòng cuối có dữ liệu" → R679 → ghi R680. Dòng mới **nằm ngoài mọi công thức SUM** và lẫn vào khối ghi chú.

**Đã sửa:** `_find_data_bounds()` dừng ở khoảng trống ≥3 dòng → vùng dữ liệu thật là R3..R663. `append()` dùng `insert_rows()` để **chèn** vào R664, đẩy khối Tổng xuống — **không ghi đè**.

Test: `tests/test_google_sheet.py::test_append_inserts_before_totals`.

---

## 5. gspread `delete_rows` — hai lần sai liên tiếp ⚠️ ĐÃ LÀM HỎNG SỔ THẬT

Đây là lỗi tôi gây ra khi test trên sổ thật. Ghi lại đầy đủ.

### Lần 1: `delete_rows(N, 1)`
```python
self.ws.delete_rows(self._data_end, 1)
```
**Lỗi:**
```
APIError 400: Invalid requests[0].deleteDimension:
endIndex[1] cannot be before startIndex[663]
```
Dòng test **không bị xoá**.

### Lần 2: `delete_rows(N, N+1)` — tưởng là "end exclusive"
```python
self.ws.delete_rows(self._data_end, self._data_end + 1)
```
Không còn lỗi 400, nhưng **xoá 2 dòng** → khối Tổng mất, xuất hiện `#REF!`.

### Nguyên nhân thật

Đọc source `gspread/worksheet.py`:
```python
def delete_rows(self, start_index, end_index=None):
    if end_index is None:
        end_index = start_index
    # gửi API:
    "startIndex": start_index - 1,   # 0-based
    "endIndex": end_index            # KHÔNG trừ 1
```

Nên `delete_rows(N, N+1)` → `startIndex=N-1, endIndex=N+1` → xoá **2 dòng**.
Còn `delete_rows(N)` → `startIndex=N-1, endIndex=N` → xoá **đúng 1 dòng**.

### Đã sửa
```python
self.ws.delete_rows(self._data_end)   # 1 tham số
```
Test regression: `test_delete_removes_exactly_one_row` — kiểm tra cả `len(grid)` giảm đúng 1 **và** `end_index is None`.

### Bài học
Fake worksheet ban đầu của tôi cũng cài sai ngữ nghĩa (tôi đoán thay vì đọc source), nên 57 unit test vẫn pass trong khi code thật sai. **Khi viết fake cho thư viện bên thứ ba, phải đọc source của nó trước.**

---

## 6. Công thức Tổng của sổ đã bỏ sót 5 dòng (lỗi có sẵn, KHÔNG do bot)

```
=SUM(C314:C658)   nhưng dữ liệu thật kéo tới R663
```

Chênh lệch tính được:

| | Trong công thức | Thực tế (tới R663) | Chênh |
|---|---|---|---|
| Thu | 230.038.332 | 231.918.332 | **+1.880.000** |
| Chi | 215.041.159 | 220.351.159 | **+5.310.000** |

5 dòng bị bỏ sót: `Lương Quỳnh`, `Lương Cường`, `P204 301 1/9 cọc`, `P102 cọc 3/9`, `P 202, 204 cọc`.

**Chủ sổ đã quyết định để nguyên, tự kiểm tra lại.** Ghi ở đây để tra cứu về sau.

> Hệ quả với bot: dòng bot ghi vào R664 cũng sẽ **không** được cộng vào Tổng, vì công thức dừng ở C658. Cần sửa thành `=SUM(C314:C670)` hoặc dùng `SUM` mở.

---

## Quy trình an toàn khi sửa sổ thật

Rút ra từ sự cố #5:

1. **Backup trước** — `python backup_sheet.py` ghi ra JSON (raw + formatted + formulas).
2. **Dry-run trước** — `python dryrun_real.py` in ra bot SẼ ghi vào đâu, không ghi gì.
3. **Test có hoàn tác** — ghi 1 dòng marker → kiểm tra → xoá → diff với backup.
4. **Diff sau mỗi thao tác** — so từng ô với backup, không tin "có vẻ đúng".
5. Nếu lệch: **`repair_final.py`** ghi lại vùng đuôi từ backup (chỉ đụng vùng đã xác minh là lệch).

### Lệnh có sẵn

```powershell
python backup_sheet.py     # backup ra backup_thu_chi_truoc_test.json
python dryrun_real.py      # xem bot sẽ ghi vào đâu (chỉ đọc)
python check_setup.py      # kiểm tra toàn bộ cấu hình
```

---

## Bảng lỗi nhanh

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `endIndex cannot be before startIndex` | `delete_rows(N, small)` | Dùng `delete_rows(N)` |
| Xoá 1 dòng mà mất 2 | `delete_rows(N, N+1)` | Dùng `delete_rows(N)` |
| `#REF!` trong ô Tổng | Dòng bị công thức tham chiếu bị xoá | `repair_final.py --apply` |
| Dòng mới nằm ngoài Tổng | Công thức SUM dừng sớm hơn dữ liệu | Sửa range công thức |
| Bot ghi vào R680 | Append ngây thơ vào dòng cuối sheet | Đã sửa: dùng `insert_rows` |
| `JSONDecodeError` khi gọi AI | Gateway trả SSE | Đã sửa: `_read_sse()` |
| `no current event loop` | Python 3.14 + PTB cũ | Pin PTB 22.8 |
