"""Giả lập môi trường Render: KHÔNG có file .env, chỉ có env vars + PORT.

Kiểm tra bot có khởi động được không trước khi user deploy thật.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 10123


def main() -> int:
    cred = (ROOT / "credentials" / "service_account.json").read_text(encoding="utf-8")
    cred_one_line = json.dumps(json.loads(cred), ensure_ascii=False)

    env = {
        # Render set các biến này
        "PORT": str(PORT),
        "RENDER": "true",
        "ENABLE_HEALTH_SERVER": "true",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        # Biến bí mật (trong thực tế điền ở Dashboard)
        "TELEGRAM_BOT_TOKEN": "9021327534:AAFNpOkU_VdWXr89DaMwE-3O-tXeT7nObpw",
        "ALLOWED_CHAT_ID": "6241137644,-5591223295",
        "SPREADSHEET_ID": "1yC47kVvWHvHfJARloXxUgf1Aacnf-YxWB8Vy5yBgNdI",
        "WORKSHEET_NAME": "Thu Chi",
        "GOOGLE_CREDENTIALS_JSON": cred_one_line,
        "AI_API_KEY": "sk-Yvh5VX2mbqfSBQCT5zmta4nZ6NsBlA5oxhIX6w2uON50rGs5",
        "AI_BASE_URL": "https://api.hermesgate.app/v1",
        "AI_MODEL": "gemini-3.8-flash-high",
        "SHEET_BACKEND": "google",
        "TIMEZONE": "Asia/Ho_Chi_Minh",
    }

    # Xoá .env khỏi biến môi trường: trên Render không có file này.
    # Ta KHÔNG xoá file thật, chỉ đảm bảo config đọc từ env.
    print("=== 1. Kiểm tra config đọc từ ENV (không cần .env) ===\n")
    check = subprocess.run(
        [sys.executable, "-c", "from soho.config import config; print(config.problems() or 'OK')"],
        cwd=ROOT,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    print(check.stdout.strip() or check.stderr.strip()[-800:])

    print("\n=== 2. Khởi động bot như Render sẽ làm ===\n")
    proc = subprocess.Popen(
        [sys.executable, "-m", "soho.bot"],
        cwd=ROOT,
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    lines: list[str] = []
    deadline = time.time() + 45
    health_ok = False
    started = False

    while time.time() < deadline:
        # đọc non-blocking
        if proc.stdout:
            line = proc.stdout.readline()
            if line:
                lines.append(line.rstrip())
                print("  |", line.rstrip())
                if "Kết nối sổ OK" in line or "Application started" in line:
                    started = True

        # thử health check
        if not health_ok:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=3) as r:
                    if r.status == 200:
                        health_ok = True
                        print(f"\n  [OK] GET /healthz -> 200 {r.read().decode()}")
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass

        if started and health_ok:
            time.sleep(2)
            break

    print("\n=== 3. Kết quả ===")
    print(f"  Bot khởi động: {'OK' if started else 'X'}")
    print(f"  Health /healthz: {'OK' if health_ok else 'X'}")

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    errors = [ln for ln in lines if "ERROR" in ln or "Traceback" in ln]
    if errors:
        print("\n  LỖI:")
        for e in errors[:10]:
            print("   ", e)

    ok = started and health_ok and not errors
    print(f"\n=== {'SẴN SÀNG DEPLOY RENDER' if ok else 'CÒN LỖI - xem trên'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
