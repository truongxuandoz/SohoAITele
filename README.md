# SoHo AI — Bot Telegram ghi sổ Excel/Google Sheet tự động

Gõ tin nhắn kiểu *"chi 159k cước hotline soho"* → AI bóc thành bút toán → bot hiện preview → bấm **✅ Ghi sổ** là dòng mới xuất hiện trong Google Sheet (hoặc file Excel).

```
Telegram message  ──►  gemini-3.8-flash-high  ──►  preview + nút bấm  ──►  Google Sheet / .xlsx
   (text hoặc ảnh)      (qua hermesgate)         (commit/edit/cancel)
```

---

## 1. Cài đặt (5 phút)

```powershell
cd C:\Users\Administrator\Documents\GitHub\SohoAITele

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Nếu PowerShell chặn activate: `Set-ExecutionPolicy -Scope Process Bypass`

---

## 2. Tạo bot với @BotFather

1. Mở Telegram, tìm **@BotFather** (có tick xanh).
2. Gửi `/newbot`.
3. Nhập **tên hiển thị**, ví dụ: `SoHo AI`.
4. Nhập **username**, phải kết thúc bằng `bot`, ví dụ: `soho_ai_ledger_bot`.
5. BotFather trả về token dạng:
   ```
   8123456789:AAH3xQ7fQ9kLmNoPqRsTuVwXyZaBcDeFgHi
   ```
   → Copy vào `.env`:
   ```
   TELEGRAM_BOT_TOKEN=8123456789:AAH3xQ7fQ9kLmNoPqRsTuVwXyZaBcDeFgHi
   ```

> 🔎 **Kiểm tra token ngay** (không cần chạy bot):
> ```powershell
> curl.exe -s "https://api.telegram.org/bot<TOKEN>/getMe"
> ```
> Phải trả `{"ok":true,...,"username":"..."}`. Nếu `{"ok":false,"error_code":401}` → token sai.

### Cấu hình thêm cho bot (nên làm)

| Gửi BotFather | Tác dụng |
|---|---|
| `/setdescription` | Mô tả bot hiện khi mở lần đầu |
| `/setcommands` | Menu lệnh — dán đúng 5 dòng dưới |
| `/setuserpic` | Ảnh đại diện |

```
start - Bắt đầu / hướng dẫn
id - Xem chat_id của cuộc trò chuyện này
tail - Xem 10 dòng cuối của sổ
undo - Xoá dòng bot vừa ghi
help - Trợ giúp
```

### Lấy `ALLOWED_CHAT_ID`

**Cách A (nhanh nhất)** — chạy bot, nhắn bất kỳ tin gì, đọc log:

```powershell
python -m soho.bot
```

Log sẽ in ra ngay:
```
INFO  chat_id=6241137644 type=private title=Do user=@truongxuando
```

Copy số đó vào `.env`:
```
ALLOWED_CHAT_ID=6241137644
```

Bot cũng trả lời lệnh `/id` cho bạn xem trực tiếp trong chat.

**Cách B** — nhắn bất kỳ tin gì cho bot rồi chạy:
```powershell
python check_setup.py
```
Nó in ra danh sách chat_id đã nhắn bot gần đây.

> Nếu dùng trong **group**, thêm bot vào group, gửi 1 tin, rồi `/id` trong group → chat_id của group là số **âm** (ví dụ `-1001234567890`).
> Nhiều người/group: `ALLOWED_CHAT_ID=6241137644,-1001234567890`

⚠️ Để **trống** `ALLOWED_CHAT_ID` nghĩa là **ai cũng dùng được bot**. Chỉ để trống khi đang test.

---

## 3. Cấu hình Google Sheet

### Bước 3.1 — Bật 2 API

Mở [Google Cloud Console](https://console.cloud.google.com/) → tạo project (hoặc chọn project có sẵn):

1. **APIs & Services → Library** → tìm `Google Sheets API` → **Enable**
2. Tìm tiếp `Google Drive API` → **Enable**

> Cần cả Drive API vì bot phải mở file theo ID.

### Bước 3.2 — Tạo Service Account

1. **APIs & Services → Credentials**
2. **+ Create Credentials → Service account**
3. Name: `soho-bot` → **Create and continue** → bỏ qua role → **Done**
4. Bấm vào service account vừa tạo → tab **Keys**
5. **Add key → Create new key → JSON** → file `.json` tự tải về

### Bước 3.3 — Đặt file key vào project

```
SohoAITele\
└── credentials\
    └── service_account.json     ← file vừa tải, đổi tên thành cái này
```

`.gitignore` đã chặn `credentials/` nên không sợ lộ key khi push.

**Kiểm tra file trước khi chạy bot:**

```powershell
python setup_google.py
```

Script này chỉ đọc, không sửa. Nó báo chính xác thiếu gì:
- `[X] Không tìm thấy file` → chưa đặt đúng chỗ
- `[X] thiếu field "private_key"` → tải nhầm file (OAuth client thay vì service account)
- `[X] 403` → chưa share sheet, hoặc share nhầm **Viewer**
- `[OK] Mở được sheet` → xong, chạy bot được

### Bước 3.4 — Share sheet cho service account

1. Mở file `service_account.json`, tìm dòng `"client_email"`:
   ```json
   "client_email": "soho-bot@my-project-123456.iam.gserviceaccount.com"
   ```
2. Mở Google Sheet của bạn → **Share** (Chia sẻ)
3. Dán email đó, chọn quyền **Editor** → **Send**

> Bỏ bước này sẽ bị lỗi `403 The caller does not have permission`.

### Bước 3.5 — Lấy `SPREADSHEET_ID`

Link sheet:
```
https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890/edit#gid=0
                                       └──────────── đây là SPREADSHEET_ID ────────────┘
```

Copy vào `.env`:
```
SPREADSHEET_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz1234567890
```

### Bước 3.6 — `WORKSHEET_NAME`

Là **tên tab** ở dưới cùng của sheet (ví dụ `Sheet1`, `SoHo`, `Thang 11`). Nếu sai tên, bot tự dùng tab đầu tiên.

```
WORKSHEET_NAME=SoHo
```

### Định dạng sheet mà bot hiểu

```
     A            B                 C          D          E
1    ...
2    Ngày tháng   Nội Dung          Thu        Chi        ghi chú     ← header ở hàng 2
3                p304 tt           1.480.000             soho
4                cước hotline                 159.000    soho
```

- Bot **tự dò tên cột** (Ngày tháng / Nội Dung / Thu / Chi / ghi chú), không phụ thuộc thứ tự.
- Header nằm ở **hàng 2** (mặc định). Nếu của bạn ở hàng khác, sửa `HEADER_ROW` trong `soho/bot.py`.
- Bot **không ghi đè** dữ liệu cũ, luôn thêm vào dòng trống ngay sau dòng cuối.
- Dòng "Tổng"/"Cộng" ở cuối sổ sẽ bị bot coi là dòng dữ liệu — nên để phần tổng ở **tab khác**.

---

## 4. Chạy bot

```powershell
.\.venv\Scripts\Activate.ps1
python check_setup.py     # kiểm tra token + sheet + AI
python -m soho.bot        # chạy bot
```

Khi thấy:
```
INFO  Bot đang chạy (model gemini-3.8-flash-high @ https://api.hermesgate.app/v1)
INFO  Kết nối sổ OK: Google Sheet: 'Sổ thu chi' / tab 'SoHo'
```
→ vào Telegram nhắn thử: `p304 tt 1.480.000 chi soho`

### Chạy 24/7 (không cần mở terminal)

**Cách 1 — Windows Task Scheduler**
```powershell
# Tạo task chạy khi đăng nhập
schtasks /create /tn "SoHoAI Bot" /tr "C:\Users\Administrator\Documents\GitHub\SohoAITele\run_bot.bat" /sc onlogon /rl highest
```

**Cách 2 — VPS / máy luôn bật**: chạy trong `tmux` hoặc `nohup`.

---

## 5. Dùng thế nào

### Một bút toán
```
p304 tt 1.480.000 chi soho
```
→ Bot hiện preview, bấm **✅ Ghi sổ**.

### Nhiều dòng cùng lúc — dán cả khối
```
11/8
p304 tt 990.000 thu
suối 10k chi tm
102, 202, 302 mibibar 70k
p301 coc 20/8 500k chi
```
→ Bot tách thành **4 dòng**, giữ đúng ngày `11/8` cho cả 4.

### Gửi ảnh sổ tay / hoá đơn
Chụp ảnh rồi gửi → bot đọc ảnh, bóc thành bút toán y như tin nhắn.

### Lệnh
| Lệnh | Việc |
|---|---|
| `/id` | Xem chat_id (để điền ALLOWED_CHAT_ID) |
| `/tail` | 10 dòng cuối của sổ |
| `/undo` | Xoá dòng bot vừa ghi (gõ `/undo 3` để xoá 3 dòng) |
| `/help` | Hướng dẫn |

### AI hiểu gì
| Bạn gõ | Bot ghi |
|---|---|
| `1.480.000` / `1,480,000` / `1480000` | 1480000 |
| `159k`, `70 nghìn` | 159000, 70000 |
| `1tr2`, `2tr5` | 1200000, 2500000 |
| `1,5tr`, `2 triệu` | 1500000, 2000000 |
| "thu", "khách trả", "hoàn ứng" | cột **Thu** |
| "chi", "trả", "mua", "cọc", "công" | cột **Chi** |

Bot còn gửi **8 dòng cuối của sổ** làm ngữ cảnh cho AI, nên nó học được cách bạn viết nội dung (`p304 tt`, `coc 14/8`…) và nhãn `soho` / `tm` / `kim`.

---

## 6. Thử không cần Telegram

```powershell
# chỉ xem AI bóc ra gì (dry-run)
python -m soho.cli "chi 159k cước hotline soho, thu 1tr2 hoàn ứng tm"

# ghi thật
python -m soho.cli "chi 159k cước hotline soho" --write
```

Chạy với file Excel local thay vì Google Sheet:

```powershell
# tạo sổ mẫu giống ảnh
python make_sample_xlsx.py

$env:SHEET_BACKEND="xlsx"
$env:XLSX_PATH="data/soho.xlsx"
python -m soho.cli "p301 coc 20/8 500k chi soho" --write
```

---

## 7. Sự cố thường gặp

| Lỗi | Nguyên nhân / cách sửa |
|---|---|
| `RuntimeError: There is no current event loop` | Python 3.14 + python-telegram-bot cũ. Đã pin `22.8` trong `requirements.txt` — chạy lại `pip install -r requirements.txt` |
| `403 The caller does not have permission` | Chưa share sheet cho `client_email` trong service_account.json, hoặc share nhầm quyền Viewer → đổi thành **Editor** |
| `404 Requested entity was not found` | `SPREADSHEET_ID` sai, hoặc `WORKSHEET_NAME` không tồn tại |
| `APIError 403: Google Sheets API has not been used` | Chưa **Enable** Sheets API (và Drive API) ở Bước 3.1 |
| `Telegram: Unauthorized` | Token sai/hết hạn → `/mybots` trong BotFather → **API Token** → Revoke & tạo mới |
| Bot không trả lời | Bot chưa chạy, hoặc đang chạy máy khác. Đảm bảo chỉ **1 instance** chạy (Telegram chỉ cho 1 poller) |
| `⛔ Chat này chưa được cấp quyền` | Thêm chat_id vào `ALLOWED_CHAT_ID`, khởi động lại bot |
| Số tiền bị sai (ra 304 thay vì 1.480.000) | Viết rõ: `p304 tt 1.480.000` — AI đọc cả câu nên thường đúng; nếu lặp lại, thêm dấu chấm phân cách nghìn |
| AI bóc ra 0 dòng | Tin nhắn không có số tiền. Kiểm tra `AI_API_KEY` / `AI_MODEL` |

---

## 8. Cấu trúc code

```
SohoAITele/
├── soho/
│   ├── ai.py        # gọi gateway OpenAI-compatible, prompt bóc bút toán, vision đọc ảnh
│   ├── money.py     # parse "1tr2", "159k", "1.480.000" → số nguyên đồng
│   ├── sheets.py    # lớp lưu trữ: GoogleSheetStore (gspread) | XlsxStore (openpyxl)
│   ├── pending.py   # preview chờ xác nhận (lưu data/pending.json, TTL 30 phút)
│   ├── config.py    # đọc .env
│   ├── bot.py       # handlers Telegram
│   └── cli.py       # thử nhanh không cần Telegram
├── web/             # bot cho website (FastAPI + widget chat)
│   ├── app.py
│   └── index.html
├── tests/           # 44 test: money, sheets, AI, handlers
├── check_setup.py   # kiểm tra token / sheet / AI
├── make_sample_xlsx.py
├── run_bot.bat      # chạy bot 1 click trên Windows
├── .env             # bí mật, KHÔNG commit
└── .env.example     # mẫu để điền
```

### Vì sao có bước preview?
Bot **không ghi thẳng** vào sổ. Nó hiện preview + 3 nút:
- **✅ Ghi sổ** → ghi vào sheet
- **✏️ Sửa** → gõ lại tin nhắn
- **❌ Huỷ** → không ghi gì

Một dòng sổ sai làm lệch cả tháng đối soát — preview là lưới an toàn. AI sai thì bạn thấy ngay trước khi nó chạm vào dữ liệu thật.

---

## 9. Bot đặt trên website (tuỳ chọn, đã có sẵn)
Không muốn dùng Telegram? Đã có sẵn web chat dùng **cùng logic** bóc/ghi:

```powershell
pip install -r requirements-web.txt
uvicorn web.app:app --reload --port 8000
```

Mở http://127.0.0.1:8000 → khung chat có nút **Ghi sổ / Huỷ**.
Đặt lên hosting (VPS, Railway, Render…) thì thêm thành domain riêng.

> Kiến trúc tách đôi: `soho/ai.py` + `soho/sheets.py` là phần lõi, dùng chung cho Telegram, web, CLI.
> Muốn thêm Zalo OA / Messenger thì chỉ viết thêm 1 lớp giao diện, không sửa lõi.

---

## 11. Deploy lên cloud

| Nền tảng | Hợp với | Ghi chú |
|---|---|---|
| **Render free** | Bot Telegram | Có `render.yaml` sẵn → xem **[DEPLOY-RENDER.md](DEPLOY-RENDER.md)**. Cần pinger chống ngủ 15 phút. |
| **VPS / Railway** | Bot Telegram | Polling 24/7, không cần sửa gì. Chỉ chạy `python -m soho.bot`. |
| **Vercel** | Bản web (`web/app.py`) | Bot Telegram **không** chạy được: polling cần process sống, filesystem read-only. |

Điểm đã sửa để chạy được trên cloud:
- Credentials qua biến `GOOGLE_CREDENTIALS_JSON` (không cần file, vì `.gitignore` chặn `credentials/`)
- `PendingStore` không crash khi filesystem read-only → fallback `/tmp` + RAM
- Có health server `/healthz` + hỗ trợ webhook

---

## 12. Mở rộng (nếu cần)

- **Webhook thay vì polling** — nhanh hơn, cần domain HTTPS. Sửa `run_polling` → `run_webhook`.
- **Thêm cột (VD "số hoá đơn")** — thêm field vào `Item` trong `ai.py`, cập nhật `SYSTEM_PROMPT` và `as_row()`.
- **Nhiều sheet theo tháng** — map `chat_id`/ngày → `WORKSHEET_NAME` khác nhau trong `build_store()`.
- **Đối soát tự động** — viết command `/check` cộng tổng Thu/Chi theo tháng từ sheet, so với sổ quỹ.
