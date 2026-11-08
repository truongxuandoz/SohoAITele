"""Dashboard giám sát bot — chạy local, xem qua trình duyệt.

    python -m soho.dashboard
    -> http://127.0.0.1:8787

Vì sao chạy local thay vì cloud: bot polling cần chạy 24/7, Render free
ngủ sau 15 phút không có traffic → bot chết. Chạy trên máy nhà thì không
bị giới hạn đó, và dashboard đọc được trạng thái thật của process.

Bảo mật: mặc định chỉ bind 127.0.0.1 nên máy khác trong LAN không vào được.
Muốn xem từ điện thoại: đặt DASHBOARD_HOST=0.0.0.0 và đặt DASHBOARD_TOKEN.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .config import config
from .heartbeat import read_status
from .supervisor import SUPERVISOR

ROOT = Path(__file__).resolve().parent.parent
STATUS_FILE = config.data_dir() / "status.json"
STARTED_AT = time.time()

HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASHBOARD_PORT", "8787"))
TOKEN = os.environ.get("DASHBOARD_TOKEN", "").strip()
AUTO_START = os.environ.get("DASHBOARD_AUTOSTART", "1") not in ("0", "false", "False")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Tự khởi động bot khi dashboard lên; dừng bot khi dashboard tắt.

    Nhờ vậy đóng cửa sổ dashboard là bot dừng theo — không để lại process mồ côi
    tranh polling với lần chạy sau.
    """
    if AUTO_START:
        SUPERVISOR.start()
    try:
        yield
    finally:
        SUPERVISOR.stop()


app = FastAPI(title="SoHo AI Monitor", docs_url=None, redoc_url=None, lifespan=lifespan)


def _check_auth(request: Request) -> None:
    """Nếu có DASHBOARD_TOKEN thì mọi lệnh điều khiển phải kèm token."""
    if not TOKEN:
        return
    given = request.headers.get("x-dashboard-token") or request.query_params.get("token")
    if not secrets.compare_digest(given or "", TOKEN):
        raise HTTPException(status_code=401, detail="token không đúng")


# ────────────────────────── API ──────────────────────────


@app.get("/api/status")
def api_status() -> JSONResponse:
    """Gộp trạng thái process (supervisor) + hoạt động bot (heartbeat)."""
    sup = SUPERVISOR.status()
    # Bot ping mỗi 30s -> 45s không ping nghĩa là đã chết.
    bot = read_status(STATUS_FILE, stale_seconds=45)

    return JSONResponse(
        {
            "server": {
                "now": time.time(),
                "uptime": round(time.time() - STARTED_AT, 1),
                "host": HOST,
                "port": PORT,
            },
            "process": sup,
            "bot": bot,
            "config": {
                "sheet_backend": config.sheet_backend,
                "spreadsheet_id": (config.spreadsheet_id or "")[:12] + "…"
                if config.spreadsheet_id
                else None,
                "worksheet": config.worksheet_name,
                "ai_model": config.ai_model,
                "ai_base_url": config.ai_base_url,
                "allowed_chats": sorted(config.allowed_chats),
                "data_dir": str(config.data_dir()),
            },
        }
    )


@app.get("/api/logs")
def api_logs(limit: int = 200) -> JSONResponse:
    return JSONResponse({"lines": SUPERVISOR.logs(limit)})


@app.post("/api/start")
def api_start(request: Request) -> JSONResponse:
    _check_auth(request)
    return JSONResponse(SUPERVISOR.start())


@app.post("/api/stop")
def api_stop(request: Request) -> JSONResponse:
    _check_auth(request)
    return JSONResponse(SUPERVISOR.stop())


@app.post("/api/restart")
def api_restart(request: Request) -> JSONResponse:
    _check_auth(request)
    return JSONResponse(SUPERVISOR.restart())


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Cho pinger / kiểm tra nhanh."""
    return JSONResponse({"ok": True, "bot": SUPERVISOR.status()["status"]})


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (ROOT / "web" / "monitor.html").read_text(encoding="utf-8")


def main() -> None:
    import uvicorn

    print(f"\n  SoHo AI Monitor  →  http://{HOST}:{PORT}\n")
    if HOST != "127.0.0.1" and not TOKEN:
        print("  ⚠️  Đang mở ra mạng LAN mà KHÔNG có DASHBOARD_TOKEN — ai cũng điều khiển được bot.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
