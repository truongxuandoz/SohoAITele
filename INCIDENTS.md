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

---

## 0c. Nguy co GHI DE khoi Tong khi cac dong trong bi lap day

### Cau hoi that
"Gia su dien kin tu dong 79 thi dong 80 dang co data (Tong) no se xu ly sao?"

### Trieu chung neu khong sua
`_find_data_bounds` cu chi dung **GAP_ROWS = 3** dong trong lam moc ket thuc.
Khi cac dong trong bi lap dan (nguoi dung xoa bot, dan de, hoac so that co
it dong trong), vung du lieu "nuot" luon khoi Tong:

```
gap = 5 -> (3, 74)  OK
gap = 4 -> (3, 74)  OK
gap = 3 -> (3, 74)  OK
gap = 2 -> (3, 81)  NGUY HIEM  <- lan 5 dong cua khoi Tong
gap = 1 -> (3, 80)  NGUY HIEM
gap = 0 -> (3, 79)  NGUY HIEM
```

Hau qua: bot chen dong moi VAO GIUA khoi Tong/doi soat, hoac ghi de len
"mang sang"/"Kim"/"tm"/"Tong tien" -> mat du lieu doi soat.

### Nguyen nhan sau xa
Chi dua vao so dong trong la gia dinh ve **dinh dang**, khong phai ve
**y nghia**. Nguoi dung hoan toan co the xoa bot dong trong ma khong biet
minh vua pha vo logic cua bot.

### Sua
Them MOC CUNG: tim dong bat dau khoi Tong (`_find_total_row`) va DUNG NGAY
khi cham dong do, khong phu thuoc gap:

```python
for idx in range(start, len(rows) + 1):
    if total_row is not None and idx >= total_row:
        break        # <- moc cung
    ...
```

Ket qua sau khi sua — an toan o MOI gap, ke ca gap = 0:

```
gap = 5 -> (3, 74) OK
gap = 4 -> (3, 74) OK
gap = 3 -> (3, 74) OK
gap = 2 -> (3, 74) OK
gap = 1 -> (3, 74) OK
gap = 0 -> (3, 74) OK
```

### Bay Unicode gap phai xu ly
So ghi `"Tồng thu chi"` (dau **o**) chu khong phai `"Tổng"` (dau **ô**).
`"tồng".startswith("tổng")` tra **False** -> phai bo dau bang `_norm()`
truoc khi so sanh.

### Bay thu hai: "mang sang"
`"mang sang"` o dong DAU vung du lieu la **but toan that** (so du dau ky),
khong phai khoi tong. Chi coi la moc tong khi xuat hien o dong > start+20.

### Them: tu mo rong khi tab het dong
`_ensure_rows()` tu goi `resize()` khi `data_end + n > row_count`, va bao
loi RO RANG khi cham `MAX_SHEET_ROWS` thay vi de Google tra
"exceeds grid limits" kho hieu.

### Regression test
`tests/test_row_limits.py` (16 test):
- gap 5/4/3/2/1/0 deu dung o R(2+N), khong lan vao khoi Tong
- chen dong o gap 2/1/0 van nam TRUOC khoi Tong
- tim dong Tong voi chu "Tồng" (Unicode)
- "mang sang" dau so la du lieu, khong phai moc tong
- "thu tong 3 phong" la but toan, khong phai dong tong
- tu mo rong khi gan het dong
- bao loi ro rang khi cham gioi han cung
---

## 0d. Cot Ngay thang bi LAP (moi ngay chi duoc ghi 1 lan)

### Trieu chung
Anh chup so that cho thay cot A lap lai `8/11/2026` nhieu lan:

```
R69: 46334  (8/11)  p301 tt
R75: 46334  (8/11)  P304 tt checkout tre
R77: 46334  (8/11)  P203, 302, tt du
```

Kiem tra tren so that: `2026-11-08` xuat hien **3 lan**.

### Nguyen nhan
`Item.as_row()` luon tra ve `ngay_thang`, nen MOI dong but toan deu mang ngay.
Nhung so cua user dung cot A lam NHAN NGAY: dong dau cua ngay co ngay,
cac dong sau trong cung ngay de TRONG.

### Yeu cau cua user (2 dieu)
1. "ung voi moi 1 ngay tren cot ngay thang thi chi co 1 lan nhap ngay thoi"
2. "kiem tra nguoc lai xem co note ngay cho cot vao ngay day chua,
    neu chua thi them vao"

### Sua
**a) `_apply_date_once()`** - chay truoc khi ghi (ca 2 backend):

```python
last_key = self._last_row_date_key()   # ngay hieu luc cua dong cuoi
for row in rows:
    key = self._date_key(row[date_col])
    if not key:
        continue                        # khong ngay -> giu nguyen
    if key == last_key:
        row[date_col] = ""              # ngay da co o dong tren -> bo
    else:
        last_key = key                  # lan dau cua ngay -> giu
```

**b) `_last_row_date_key()` phai TRACE NGUOC**
Dong cuoi cung thuong KHONG co ngay (vi ngay ghi o dong dau cua ngay do).
Doc thang dong cuoi luon ra rong -> phai doc lai tu `_data_start` den
`_data_end` va lay ngay cuoi cung tim duoc. (Bug nay lam test fail 1 lan.)

**c) Kiem tra nguoc: `ensure_date_present()`**
Truoc khi ghi, kiem tra ngay user noi co trong so chua:
- Neu CHUA -> ghi ngay vao cot A (khong duoc de trong, vi trong = thuoc
  ngay cua dong phia tren -> SAI ngay)
- Neu DA co -> de trong, va hien ghi chu trong preview:
  "Ngay 08/11/2026 da co trong so (dong 69) - cot Ngay de trong."

**d) `extract_date_from_text()`** - AI khong dien ngay nhung user co noi
-> tu trich: `9/11`, `08/11/2026`, `hom qua`, `2 ngay truoc`.

### Test
`tests/test_dates.py` (26 test):
- lo 3 dong cung ngay -> chi dong dau mang ngay
- ngay da co trong so -> khong ghi lap
- ngay moi -> duoc ghi
- lo tron 2 ngay -> moi ngay 1 lan
- `append()` thuc su ghi trong cho dong cung ngay
- kiem tra nguoc: tim thay / khong tim thay ngay
- ngay tuong doi: hom nay/hom qua/hom kia/N ngay truoc/mai
---

## 0e. Anh hoa don ghi LAP ngay + nam sai (2024 thay vi 2026)

### Trieu chung
User gui anh hoa don SHB kem caption `/ghi P304 tt checkout tre, 2 nc suoi, 70k van`.
Bot ghi vao R78 voi ngay `08/11/2024` — trong khi R69 da co `8/11` (2026).
Cot Ngay bi lap lan thu 4.

### Hai nguyen nhan

**a) `on_photo` KHONG kiem tra ngay**
Nhanh nhap tay (`_handle_text`) goi `ensure_date_present()`, nhung nhanh anh
(`on_photo`) thi khong. Nen anh ghi thang vao so ma khong dedup ngay.

**b) Model vision doan SAI NAM**
Hoa don hien thi thang 11 nam 2026, nhung model dien `08/11/2024` (mau nam cu).
`_date_key('08/11/2024')` -> `2024-11-08` != `2026-11-08` -> dedup KHONG khop
-> ghi lap.

### Sua

**a) `on_photo` goi `ensure_date_present()`** giong het nhanh nhap tay:

```python
date_notes = ensure_date_present(items, STORE, caption)
await _send_preview(message, items, note, chat_id, date_notes=date_notes)
```

**b) So sanh theo THANG-NGAY, khong theo nam**

```python
@staticmethod
def _day_key(key):        # '2024-11-08' -> '11-08'
    return key[5:10] if len(key) >= 10 else ''
```

Ly do: moi TAB cua so la MOT THANG. `08/11` trong tab T11 luon la cung mot
ngay du AI ghi nam 2024 hay 2026. So sanh thang-ngay ben hon va mien nhiem
voi loi model doan sai nam.

**c) `_normalize_year()`** - sua nam lech qua 1 nam ve nam hien tai, de
gia tri GHI VAO O cung dung (khong chi dedup dung):

```
08/11/2024 -> 2026-11-08   (ghi vao o)
09/11/2024 -> 2026-11-09
```

### Test
- `tests/test_dates.py::TestYearBugFromPhoto` (6 test): normalize nam,
  day_key bo qua nam, anh 2024 khong lap, ngay moi duoc sua nam,
  `date_exists_in_sheet` khop qua cac nam
- `tests/test_photo_group.py::TestPhotoDateRules` (3 test): on_photo goi
  ensure_date_present, ghi chu ngay hien trong preview, loi kiem tra ngay
  khong chan ghi so