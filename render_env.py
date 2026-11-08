"""In ra các giá trị env cần dán vào Render Dashboard.

    python render_env.py            # in giá trị, che bớt secret
    python render_env.py --full     # in đầy đủ (cẩn thận: lộ secret trên màn hình)
    python render_env.py --json     # in JSON 1 dòng để dán vào GOOGLE_CREDENTIALS_JSON
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def mask(value: str, keep: int = 6) -> str:
    if not value:
        return "(trống)"
    if len(value) <= keep * 2:
        return value[:keep] + "***"
    return f"{value[:keep]}...{value[-4:]}  (dài {len(value)})"


def main() -> int:
    full = "--full" in sys.argv
    as_json = "--json" in sys.argv

    # Đọc .env local
    env: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()

    cred_file = ROOT / "credentials" / "service_account.json"

    if as_json:
        if not cred_file.exists():
            print(f"KHÔNG thấy {cred_file}", file=sys.stderr)
            return 1
        info = json.loads(cred_file.read_text(encoding="utf-8"))
        # 1 dòng, giữ nguyên \n trong private_key
        print(json.dumps(info, ensure_ascii=False, separators=(",", ":")))
        return 0

    print("=" * 70)
    print("DÁN CÁC GIÁ TRỊ SAU VÀO RENDER DASHBOARD > Environment")
    print("=" * 70)
    print()

    keys = [
        ("TELEGRAM_BOT_TOKEN", "từ @BotFather"),
        ("ALLOWED_CHAT_ID", "chat riêng + group, cách nhau dấu phẩy"),
        ("SPREADSHEET_ID", "phần giữa /d/ và /edit"),
        ("WORKSHEET_NAME", "tên tab (có thể có dấu cách cuối)"),
        ("GOOGLE_CREDENTIALS_JSON", "dùng --json bên dưới để lấy"),
        ("AI_API_KEY", "gateway OpenAI-compatible"),
        ("AI_BASE_URL", ""),
        ("AI_MODEL", ""),
        ("SHEET_BACKEND", "google"),
        ("ENABLE_HEALTH_SERVER", "true"),
        ("TIMEZONE", "Asia/Ho_Chi_Minh"),
    ]

    for key, note in keys:
        if key == "GOOGLE_CREDENTIALS_JSON":
            if cred_file.exists():
                size = len(cred_file.read_text(encoding="utf-8"))
                value = f"<{size} bytes, xem lệnh bên dưới>"
            else:
                value = "(chưa có file credentials)"
        elif key in ("SHEET_BACKEND", "ENABLE_HEALTH_SERVER"):
            value = env.get(key) or ("google" if key == "SHEET_BACKEND" else "true")
        elif key == "TIMEZONE":
            value = env.get(key) or "Asia/Ho_Chi_Minh"
        else:
            raw = env.get(key, "")
            value = raw if full else mask(raw)

        suffix = f"   ← {note}" if note else ""
        print(f"{key}")
        print(f"    {value}{suffix}")
        print()

    print("=" * 70)
    print("LẤY GOOGLE_CREDENTIALS_JSON (1 dòng, dán nguyên vào Render):")
    print("=" * 70)
    print()
    print("    python render_env.py --json")
    print()
    print("  Rồi copy toàn bộ output (1 dòng JSON) vào ô value của")
    print("  GOOGLE_CREDENTIALS_JSON trong Render.")
    print()
    print("=" * 70)
    print("LƯU Ý:")
    print("  - KHÔNG set PORT. Render tự set.")
    print("  - KHÔNG dùng SHEET_BACKEND=xlsx (filesystem Render tạm thời).")
    print("  - Đặt ENABLE_HEALTH_SERVER=true để /healthz hoạt động.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
