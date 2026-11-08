# Deploy Render — hướng dẫn cho repo này

Bot local đã tắt. Làm theo đúng thứ tự dưới đây.

---

## Trước khi bắt đầu

✅ Bot local đã tắt (không còn process `soho.bot`)
✅ Code đã push lên `github.com/truongxuandoz/SohoAITele`
✅ `render.yaml` có sẵn, đã kiểm chứng bằng giả lập Render

⚠️ **Chỉ chạy bot ở 1 nơi.** Telegram chỉ cho 1 poller — nếu vừa local vừa Render,
tin nhắn sẽ mất ngẫu nhiên.

---

## Bước 1 — Lấy giá trị env

```powershell
cd C:\Users\Administrator\Documents\GitHub\SohoAITele
.\.venv\Scripts\python.exe render_env.py
```

In ra danh sách biến (secret được che). Để lấy JSON credentials:

```powershell
.\.venv\Scripts\python.exe render_env.py --json
```

Output là **1 dòng JSON** — copy toàn bộ, đó là giá trị cho `GOOGLE_CREDENTIALS_JSON`.

> Nếu cần xem giá trị đầy đủ: `render_env.py --full` (cẩn thận lộ secret trên màn hình).

---

## Bước 2 — Tạo service trên Render

1. [dashboard.render.com](https://dashboard.render.com) → đăng nhập bằng GitHub
2. **New** → **Blueprint**
3. Chọn repo `truongxuandoz/SohoAITele`
4. Render đọc `render.yaml` → bấm **Apply**

> Nếu không thấy Blueprint, dùng **New → Web Service**:
> | Field | Giá trị |
> |---|---|
> | Language | Python 3 |
> | Region | Singapore |
> | Build Command | `pip install -r requirements.txt` |
> | Start Command | `python -m soho.bot` |
> | Plan | Free |
> | Health Check Path | `/healthz` |

---

## Bước 3 — Điền Environment Variables

Vào service → tab **Environment** → **Add Environment Variable**.

Dán từng cặp từ output `render_env.py`:

| Key | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | từ @BotFather |
| `ALLOWED_CHAT_ID` | `6241137644,-5591223295` |
| `SPREADSHEET_ID` | `1yC47kVvWHvHfJARloXxUgf1Aacnf-YxWB8Vy5yBgNdI` |
| `WORKSHEET_NAME` | `Thu Chi` |
| `GOOGLE_CREDENTIALS_JSON` | 1 dòng JSON từ `--json` |
| `AI_API_KEY` | `sk-...` |
| `AI_BASE_URL` | `https://api.hermesgate.app/v1` |
| `AI_MODEL` | `gemini-3.8-flash-high` |

Blueprints đã khai báo sẵn `SHEET_BACKEND=google` và `ENABLE_HEALTH_SERVER=true`.

> ℹ️ `WORKSHEET_NAME=Thu Chi` — tab thật tên `"Thu Chi "` có **dấu cách cuối**.
> Code tự khớp tên kể cả thừa/thiếu dấu cách, nên điền `Thu Chi` là được.

> ⚠️ **KHÔNG set `PORT`.** Render tự set. Code đã đọc biến đó.

---

## Bước 4 — Deploy và kiểm tra

Bấm **Manual Deploy → Deploy latest commit**.

Theo dõi **Logs**, phải thấy:

```
INFO  Đã đặt menu lệnh: ghi, id, tail, undo, start, help
INFO  Kết nối sổ OK: Google Sheet: 'soho boutique' / tab 'Thu Chi '
INFO  Bot đang chạy (model gemini-3.8-flash-high @ ...)
INFO  Health server trên cổng 10000 (GET /healthz)
```

Kiểm tra health:
```powershell
curl.exe -s "https://<service>.onrender.com/healthz"
```
Phải trả `ok`.

Rồi nhắn thử bot trên Telegram: `/id`

---

## Bước 5 — Chống ngủ 15 phút (BẮT BUỘC)

Render free **spin down sau 15 phút không có traffic**. Bot dùng polling nên
Render thấy "không ai gọi" → cho ngủ → bot chết.

### cron-job.org (free)

1. [cron-job.org](https://cron-job.org) → đăng ký
2. **Create cronjob**:
   - URL: `https://<service>.onrender.com/healthz`
   - Schedule: **every 10 minutes**
3. Save → **TEST RUN** phải trả `200 ok`

### Kiểm tra pinger hoạt động

```powershell
Measure-Command { Invoke-WebRequest "https://<service>.onrender.com/healthz" -UseBasicParsing }
```

- Lần đầu sau ngủ: ~60 giây
- Các lần sau: < 1 giây

Nếu lần nào cũng ~60s → pinger không chạy.

---

## Sau khi deploy xong

1. **Tắt bot local** (đã tắt) — đừng chạy lại
2. Thử trong Telegram:
   - Chat riêng: `p304 tt 1.480.000 chi soho`
   - Group: `/ghi p304 tt 1.480.000 chi soho`
3. Kiểm tra Google Sheet có dòng mới đúng chỗ (chèn trước khối Tổng)

---

## Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Sửa |
|---|---|---|
| Build fail: `ModuleNotFoundError` | Thiếu package | Kiểm tra `requirements.txt` |
| Log: `Không kết nối được sổ` | `GOOGLE_CREDENTIALS_JSON` sai | Lấy lại bằng `render_env.py --json` |
| `403 The caller does not have permission` | Chưa share sheet | Share cho `soho-bot@internet-cafe-452807.iam.gserviceaccount.com` quyền **Editor** |
| Bot im sau ~15 phút | Chưa có pinger | Làm bước 5 |
| Bot không trả lời gì | 2 nơi cùng chạy | Tắt bản local |
| `/healthz` trả 404 | `ENABLE_HEALTH_SERVER` chưa `true` | Thêm env var, redeploy |
| Hết 750 giờ giữa tháng | Nhiều service free | Xoá bớt service không dùng |

### Xem log trên Render

Dashboard → service → **Logs**. Hoặc:

```powershell
# cài Render CLI nếu cần
render logs --resources srv-xxxxx --tail
```

---

## Đã kiểm chứng trước khi deploy

Tôi đã chạy `simulate_render.py` — giả lập môi trường Render thật
(không có file `.env`, chỉ có env vars + `PORT`):

```
=== 1. Kiểm tra config đọc từ ENV (không cần .env) ===
OK

=== 2. Khởi động bot như Render sẽ làm ===
  | Đã đặt menu lệnh: ghi, id, tail, undo, start, help
  | Kết nối sổ OK: Google Sheet: 'soho boutique' / tab 'Thu Chi '
  [OK] GET /healthz -> 200 ok

=== SẴN SÀNG DEPLOY RENDER ===
```

Nghĩa là code đã sẵn sàng — không cần sửa gì thêm.

---

## Hạn chế cần biết trên Render free

| | |
|---|---|
| CPU / RAM | 0.1 CPU / 512 MB |
| Giờ/tháng | 750 (≈ 31 ngày; 1 service 24/7 vừa đủ) |
| Ngủ sau 15 phút idle | ⚠️ Có — cần pinger |
| Filesystem | Tạm thời — `data/pending.json` mất khi restart |
| Persistent disk | ❌ Không |
| HTTPS | ✅ Tự động |

**`pending.json` mất khi restart:** nếu bot hiện preview mà chưa bấm Ghi sổ, rồi Render restart,
bấm Ghi sổ sẽ báo "hết hạn". Tránh bằng cách bấm Ghi sổ ngay.

Muốn state bền: thêm Upstash Redis (free 10k lệnh/ngày) và đổi `PendingStore`
sang Redis — code đã tách class này nên chỉ sửa 1 file.
