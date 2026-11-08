# Sự cố đã gặp & cách phòng tránh

Ghi lại các lỗi thật đã xảy ra khi đưa bot vào sổ thật, để không lặp lại.

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
