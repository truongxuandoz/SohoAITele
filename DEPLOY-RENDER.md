# Deploy bot lên Render (free tier)

Tài liệu này dành cho **bot Telegram (polling)**, đã sửa code để chạy được trên Render free.

> Tóm tắt: **được, nhưng free tier có 1 cái bẫy phải xử lý** — service ngủ sau 15 phút.
> Xem [mục 4](#4-chống-ngủ-15-phút-bắt-buộc).

---

## 1. Free tier được gì, mất gì

Theo [docs Render](https://render.com/docs/free):

| | Free |
|---|---|
| CPU / RAM | 0.1 CPU / 512 MB |
| Giá | $0 |
| Giờ/tháng | 750 giờ mỗi workspace |
| **Ngủ sau 15 phút không có request** | ⚠️ **Có** — thức lại mất ~1 phút |
| Filesystem | Tạm thời — mất khi deploy/restart/ngủ |
| Persistent disk | ❌ Không |
| Custom domain | ✅ 2 cái |
| HTTPS | ✅ tự động |

**750 giờ ≈ 31 ngày.** Một service chạy 24/7 vừa đúng 744 giờ → lọt. Nhưng nếu bạn có **2 service free** chạy cùng lúc thì hết quota giữa tháng và Render treo cả hai.

**Điểm quan trọng:** bot Telegram dùng **polling** — nó chủ động hỏi Telegram, không nhận request từ ngoài. Render thấy "không có inbound traffic" → **cho ngủ sau 15 phút** → bot chết. Phải có pinger (mục 4).

---

## 2. Sửa code đã làm sẵn

Tôi đã sửa 3 chỗ khiến bot không chạy được trên cloud:

| Trước | Sau |
|---|---|
| `PendingStore` gọi `mkdir()` lúc import → crash | Bắt `OSError`, fallback sang `/tmp`, hoạt động tiếp trong RAM |
| Credentials chỉ đọc từ **file** (bị `.gitignore` chặn) | Thêm `GOOGLE_CREDENTIALS_JSON` — dán JSON vào env var |
| `run_polling()` không có HTTP server | Thêm health server `/healthz` trên `PORT` + hỗ trợ webhook |

Riêng **backend `xlsx` bị chặn có chủ đích** trên cloud: filesystem tạm thời, ghi xong mất. `check_setup.py` sẽ báo lỗi nếu bạn chọn nó.

---

## 3. Deploy từng bước

### 3.1 Đẩy code lên GitHub

```powershell
cd C:\Users\Administrator\Documents\GitHub\SohoAITele
git add .
git commit -m "SoHo AI bot"
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

Kiểm tra `.env` **không** bị commit:
```powershell
git ls-files | Select-String "\.env$"
# phải KHÔNG có kết quả
```

### 3.2 Tạo service trên Render

**Cách A — Blueprint (dùng `render.yaml` có sẵn)**

1. [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint**
2. Chọn repo → Render đọc `render.yaml` → **Apply**

**Cách B — thủ công**

1. **New → Web Service** → chọn repo
2. Điền:

| Field | Giá trị |
|---|---|
| Language | `Python 3` |
| Region | `Singapore` (gần VN nhất) |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -m soho.bot` |
| Plan | **Free** |
| Health Check Path | `/healthz` |

### 3.3 Điền biến môi trường

Vào **Environment** của service, thêm:

| Key | Giá trị |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token từ @BotFather |
| `ALLOWED_CHAT_ID` | chat_id của bạn (xem README mục 2) |
| `SPREADSHEET_ID` | phần giữa `/d/` và `/edit` |
| `WORKSHEET_NAME` | tên tab, ví dụ `SoHo` |
| `GOOGLE_CREDENTIALS_JSON` | **dán nguyên nội dung** `service_account.json` |
| `AI_API_KEY` | `sk-...` |
| `AI_BASE_URL` | `https://api.hermesgate.app/v1` |
| `AI_MODEL` | `gemini-3.8-flash-high` |
| `SHEET_BACKEND` | `google` |
| `ENABLE_HEALTH_SERVER` | `true` |

> ⚠️ **Đừng set `PORT`.** Render tự set. Code đã đọc biến đó.

**Cách dán `GOOGLE_CREDENTIALS_JSON` cho đúng:**

```powershell
# In ra 1 dòng JSON đã nén, copy toàn bộ rồi dán vào Render
(Get-Content credentials/service_account.json -Raw | ConvertFrom-Json | ConvertTo-Json -Compress)
```

JSON phải giữ nguyên `\n` trong `private_key`. `ConvertTo-Json` xử lý đúng việc này.

### 3.4 Deploy

Bấm **Manual Deploy → Deploy latest commit**. Theo dõi log, phải thấy:

```
INFO  Kết nối sổ OK: Google Sheet: 'Sổ thu chi' / tab 'SoHo'
INFO  Bot đang chạy (model gemini-3.8-flash-high @ ...)
INFO  Health server trên cổng 10000 (GET /healthz)
```

Rồi nhắn thử bot trên Telegram.

---

## 4. Chống ngủ 15 phút (BẮT BUỘC)

Không làm bước này → bot im lặng sau 15 phút, mất ~1 phút mới trả lời.

### Cách 1 — cron-job.org (free, dễ nhất)

1. [cron-job.org](https://cron-job.org) → đăng ký free
2. **Create cronjob**:
   - URL: `https://<service>.onrender.com/healthz`
   - Schedule: **every 10 minutes**
3. Save → bấm **TEST RUN** phải trả `200 ok`

### Cách 2 — UptimeRobot (free)

1. [uptimerobot.com](https://uptimerobot.com) → **Add New Monitor**
2. Monitor Type: `HTTP(s)`
3. URL: `https://<service>.onrender.com/healthz`
4. Interval: `10 minutes`

> Cả hai đều free và đủ dùng. Đặt 10 phút vì Render ngủ ở phút 15 — cần biên an toàn.

### Vì sao `/healthz` chứ không phải `/`?

`/` trên Render free khi service đang ngủ sẽ trả trang loading của Render. `/healthz` do code mình phục vụ, trả `200 ok` ngay, và **đánh thức** service.

### Kiểm tra pinger có tác dụng

```powershell
# Gọi /healthz, đo thời gian phản hồi
Measure-Command { Invoke-WebRequest "https://<service>.onrender.com/healthz" -UseBasicParsing }
```

- Lần đầu sau khi ngủ: ~60 giây (đang thức dậy)
- Các lần sau: < 1 giây

Nếu lần nào cũng ~60s → pinger không chạy.

---

## 5. Hạn chế cần biết

### State `pending` mất khi restart

`data/pending.json` nằm trên filesystem tạm. Render restart → mất. Nghĩa là:

- Bạn gõ tin nhắn, bot hiện preview, **chưa bấm Ghi sổ**
- Render restart (deploy mới, hoặc hết RAM)
- Bấm **Ghi sổ** → "Phiên chờ đã hết hạn"

**Cách tránh:** bấm Ghi sổ ngay sau khi xem preview. Với sổ thu chi thì đây là thói quen tốt.

> Muốn state bền thật: thêm Upstash Redis (free 10k lệnh/ngày) và đổi `PendingStore` sang đọc/ghi Redis. Code đã tách riêng class này nên chỉ sửa 1 file.

### 0.1 CPU / 512 MB

Đủ cho bot này (chủ yếu chờ mạng). Nhưng nếu bạn gửi **ảnh sổ tay**, model vision cần thêm thời gian — có thể chạm giới hạn. Theo dõi tab **Metrics**.

### Render có thể restart bất cứ lúc nào

Free tier không cam kết uptime. Bot tự khởi động lại (polling loop), nhưng tin nhắn gửi đúng lúc restart có thể mất.

### Không có Shell/SSH trên free

Không vào được container để debug. Dùng **Logs** trong Dashboard.

---

## 6. Phương án khác nếu Render free không đủ

| Nền tảng | Giá | Ưu | Nhược |
|---|---|---|---|
| **Render free** | $0 | Dễ nhất, có `render.yaml` sẵn | Ngủ 15 phút, cần pinger |
| **Render Starter** | $7/tháng | Không ngủ, ổn định | Tốn tiền |
| **Fly.io** | ~$0–2 | Không ngủ nếu cấu hình đúng | Cần CLI, phức tạp hơn |
| **VPS (Vultr/DigitalOcean)** | $4–6/tháng | Toàn quyền, không giới hạn | Tự cài, tự bảo trì |
| **Railway** | $5 credit/tháng | Rất dễ, không ngủ | Hết credit thì dừng |
| **Máy nhà + Cloudflare Tunnel** | $0 | Free, không ngủ, toàn quyền | Máy phải bật 24/7 |

**Khuyến nghị:** bắt đầu bằng **Render free + cron-job.org**. Nếu 1 tháng thấy ổn định và dùng thật, nâng lên **Render Starter $7** — bỏ được pinger và state bền hơn.

---

## 7. Troubleshooting

| Triệu chứng | Nguyên nhân | Sửa |
|---|---|---|
| Deploy fail: `ModuleNotFoundError` | Thiếu package trong `requirements.txt` | Thêm vào rồi push |
| Log: `Không kết nối được sổ: ...` | `GOOGLE_CREDENTIALS_JSON` sai định dạng | Nén lại bằng lệnh ở 3.3 |
| Log: `403 The caller does not have permission` | Chưa share sheet cho `client_email` | Share quyền **Editor** |
| Bot im sau ~15 phút | Chưa có pinger | Làm mục 4 |
| Bot không trả lời gì | Đang chạy 2 nơi (máy local + Render) | Tắt bản local — Telegram chỉ cho 1 poller |
| `⛔ Chat này chưa được cấp quyền` | `ALLOWED_CHAT_ID` chưa đúng | Nhắn `/id` cho bot, copy số vào env, redeploy |
| `/healthz` trả 404 | `ENABLE_HEALTH_SERVER` chưa `true` | Thêm env var, redeploy |
| Hết 750 giờ giữa tháng | Có nhiều service free | Xoá bớt service không dùng |
| `Phiên chờ đã hết hạn` | Service restart giữa lúc preview | Bấm Ghi sổ ngay |

### Xem log

Dashboard → service → **Logs**. Hoặc dùng CLI:
```powershell
render logs --resources srv-xxxxx --tail
```

---

## 8. Checklist trước khi bấm Deploy

- [ ] `.env` **không** có trong git (`git ls-files | Select-String "\.env$"` → trống)
- [ ] Đã có `GOOGLE_CREDENTIALS_JSON` (1 dòng nén)
- [ ] Đã share Google Sheet cho `client_email` quyền **Editor**
- [ ] `SHEET_BACKEND=google` (không phải `xlsx`)
- [ ] `ENABLE_HEALTH_SERVER=true`
- [ ] KHÔNG set `PORT`
- [ ] Đã tạo cron-job.org gọi `/healthz` mỗi 10 phút
- [ ] Đã tắt bot chạy ở máy local
