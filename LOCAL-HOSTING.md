# Chạy bot trên máy nhà + Dashboard giám sát

Bot chạy **trên máy Windows của bạn** (không phải cloud). Có dashboard web để xem
trạng thái và bật/tắt bot mà không cần mở terminal.

## Vì sao không dùng Render free

| | Render free | Máy nhà |
|---|---|---|
| Ngủ sau 15 phút | ⚠️ **Có** — bot polling chết | ✅ Không |
| Giờ/tháng | 750 | Không giới hạn |
| Filesystem | Tạm thời | Bền |
| Cần pinger cron-job.org | ✅ Bắt buộc | ❌ Không |
| Máy tắt → bot chết | ✅ Chạy 24/7 | ⚠️ Có |

Bot dùng **polling** (không phải webhook) nên Render thấy "không có traffic vào"
→ cho ngủ → bot chết. Pinger đánh thức được nhưng mỗi lần ngủ dậy mất ~60 giây,
tin nhắn trong lúc đó có thể bị lỡ. Chạy máy nhà tránh hẳn vấn đề này.

---

## Chạy trong 1 bước

```
SohoAITele\run_server.bat
```

Rồi mở: **http://127.0.0.1:8787**

File `.bat` tự:
1. Tạo venv nếu chưa có
2. Cài dependencies
3. Chạy dashboard
4. Dashboard tự khởi động bot

Đóng cửa sổ = bot dừng.

---

## Dashboard có gì

### Thẻ trạng thái
- **Đang chạy** (xanh, nhấp nháy) / **Đã dừng** (xám) / **Đã chết** (đỏ)
- **Uptime** + pid thật
- **Số lần restart** tự động

### Số liệu
| Thẻ | Ý nghĩa |
|---|---|
| Tin nhắn nhận | Số tin bot đã xử lý |
| AI calls | Số lần gọi model |
| Bút toán đã ghi | Số dòng đã ghi vào Google Sheet |
| Đã bóc | Số bút toán AI bóc được (chưa ghi) |
| Lỗi | Số lỗi + lỗi gần nhất |

### Nhật ký hoạt động
Log realtime từng sự kiện: nhận tin, bóc bút toán, ghi sổ, lỗi.

### Cấu hình
Hiển thị backend, Sheet ID, tab, model, chat được phép, và **trạng thái kết nối sổ**.

### Log bot
Toàn bộ stdout/stderr của bot, cập nhật mỗi 5 giây.

### Nút điều khiển
- ▶ **Khởi động** — bật bot
- ⟳ **Khởi động lại** — tắt rồi bật (dùng khi bot treo)
- ■ **Dừng** — tắt bot (có hỏi xác nhận)

---

## Tự khởi động cùng Windows

```powershell
# Mở PowerShell as Administrator
cd C:\Users\Administrator\Documents\GitHub\SohoAITele
powershell -ExecutionPolicy Bypass -File install_autostart.ps1
```

Tạo Scheduled Task chạy khi đăng nhập Windows (trễ 30 giây cho mạng sẵn sàng).

Thử ngay không cần reboot:
```powershell
Start-ScheduledTask -TaskName "SoHo AI Monitor"
```

Gỡ bỏ:
```powershell
powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove
```

---

## Ba lớp bảo vệ

Bot polling phải chạy liên tục, nên có 3 cơ chế:

### 1. Supervisor — tự khởi động lại khi bot crash

Bot chết (mất mạng, hết RAM, lỗi code) → supervisor phát hiện trong 3 giây → spawn lại.

Backoff tăng dần: `2s → 5s → 10s → 20s → 30s → 60s`

Nếu bot chạy ổn > 60 giây, backoff reset về 2s.

**Bảo vệ chống crash loop:** quá 20 lần restart trong 5 phút → dừng tự động, báo lỗi trên dashboard. Không để máy bạn bị spam process.

### 2. Windows Job Object — không để bot mồ côi

Đóng dashboard (kể cả `taskkill /F`) → bot chết theo.

Không có cơ chế này thì bot cũ ở lại, và **2 bot cùng poll Telegram** → tin nhắn
mất ngẫu nhiên, rất khó debug. Job object là cơ chế của OS nên kill cứng vẫn sạch.

### 3. Heartbeat — biết bot còn sống thật

Bot ghi `data/status.json` mỗi 30 giây. Dashboard đọc file đó:
- Cập nhật < 45s → bot sống
- Cũ hơn → bot treo (process còn nhưng không phản hồi)

Phân biệt được **"im vì không ai nhắn"** với **"chết"**.

---

## Kiểm tra bot có đang chạy không

### Qua dashboard
Mở http://127.0.0.1:8787 — thẻ trạng thái phải xanh.

### Qua dòng lệnh
```powershell
# Process còn không
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like "*soho.bot*" } |
  Select-Object ProcessId,CreationDate

# Heartbeat
Get-Content data\status.json | ConvertFrom-Json |
  Select-Object pid,alive,uptime_seconds,seconds_since_update
```

### Qua Telegram
Nhắn `/id` cho bot. Không trả lời = bot không chạy.

---

## Sự cố

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| Dashboard không mở | Port 8787 bị chiếm | Đổi `DASHBOARD_PORT=8788` trong `.env` |
| Bot im, dashboard xanh | Telegram không gửi tin (privacy mode) | Dùng `/ghi` trong group |
| Bot restart liên tục | Lỗi cấu hình (thiếu token, sai sheet) | Xem panel Log bot |
| `restart quá 20 lần` | Crash loop | Sửa lỗi gốc rồi bấm Khởi động lại |
| Bot chết khi đóng dashboard | **Đúng thiết kế** | Bật lại bằng `run_server.bat` |
| Muốn bot chạy dù dashboard tắt | Chạy `python -m soho.bot` riêng | Không có dashboard giám sát |
| Sau reboot không tự chạy | Chưa cài autostart | Chạy `install_autostart.ps1` |

### Xem từ điện thoại trong LAN

Mặc định chỉ `127.0.0.1` (máy này). Muốn mở cho LAN:

```
# .env
DASHBOARD_HOST=0.0.0.0
DASHBOARD_TOKEN=chuoi-bi-mat-tu-nghi
```

Rồi vào `http://<ip-may-tinh>:8787?token=chuoi-bi-mat-tu-nghi`

⚠️ **Bắt buộc có token** khi mở ra LAN — không thì ai trong mạng cũng bật/tắt bot được.

Tìm IP máy:
```powershell
(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike "127.*"}).IPAddress
```

---

## Cấu trúc file

```
soho/
  heartbeat.py    # bot ghi trạng thái ra data/status.json
  supervisor.py   # quản lý process bot: start/stop/restart + auto-recovery
  dashboard.py    # FastAPI server + API
web/
  monitor.html    # giao diện dashboard
data/
  status.json     # heartbeat (bot ghi, dashboard đọc)
  bot.log         # log bot
run_server.bat        # chạy dashboard (+ bot)
run_bot.bat           # chạy bot trơn, không dashboard
install_autostart.ps1 # cài/gỡ tự khởi động Windows
```

## API (dùng được bằng script)

| Method | Endpoint | Việc |
|---|---|---|
| GET | `/api/status` | Trạng thái đầy đủ |
| GET | `/api/logs?limit=N` | Log bot |
| POST | `/api/start` | Bật bot |
| POST | `/api/stop` | Tắt bot |
| POST | `/api/restart` | Khởi động lại |
| GET | `/healthz` | Kiểm tra nhanh |

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/status | ConvertTo-Json -Depth 5
```

## Test

`tests/test_supervisor.py` (19 test) — heartbeat, state, crash recovery, orphan prevention.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_supervisor.py -v
```

## Đã kiểm chứng thật

| Kịch bản | Kết quả |
|---|---|
| Dashboard tự khởi động bot | ✅ pid mới, heartbeat OK |
| Kill bot → tự spawn lại | ✅ 8 giây, pid mới |
| Stop qua API | ✅ process sạch |
| Restart từ stopped | ✅ chạy lại |
| **taskkill /F dashboard** | ✅ bot chết theo, không mồ côi |
| Google Sheet kết nối | ✅ `'soho boutique' / tab 'Thu Chi '` |

Hai bug đã tìm thấy và sửa trong quá trình test:

1. **Supervisor không spawn lại được** — `self._proc` không được xoá khi bot chết,
   điều kiện `_proc is not None` làm vòng lặp `continue` mãi, status kẹt `restarting`
2. **Bot mồ côi** — kill cứng dashboard để lại bot tranh polling; sửa bằng Job Object

Cả hai đều có regression test.
