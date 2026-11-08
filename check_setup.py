"""Kiểm tra cấu hình: Telegram token, Google Sheet, AI gateway. Chạy: python check_setup.py"""

from __future__ import annotations

import json
import sys
import urllib.request

from soho.config import config


def check_env() -> bool:
    problems = config.problems()
    print("── ENV ──")
    print(f"  model      : {config.ai_model}")
    print(f"  base_url   : {config.ai_base_url}")
    print(f"  backend sổ : {config.sheet_backend}")
    if problems:
        for p in problems:
            print(f"  ❌ {p}")
        return False
    print("  ✅ đủ biến môi trường")
    return True


def check_telegram() -> tuple[bool, str]:
    print("── Telegram ──")
    if not config.telegram_token:
        print("  ❌ chưa có TELEGRAM_BOT_TOKEN")
        return False, ""
    url = f"https://api.telegram.org/bot{config.telegram_token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.load(resp)
    except Exception as exc:
        print(f"  ❌ lỗi gọi API: {exc}")
        return False, ""
    if not data.get("ok"):
        print(f"  ❌ Telegram từ chối token: {data}")
        return False, ""
    me = data["result"]
    print(f"  ✅ bot @{me.get('username')} (id {me.get('id')})")
    return True, me.get("username", "")


def check_ai() -> bool:
    print("── AI gateway ──")
    req = urllib.request.Request(
        f"{config.ai_base_url}/models", headers={"Authorization": f"Bearer {config.ai_api_key}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except Exception as exc:
        print(f"  ❌ {exc}")
        return False
    ids = [m.get("id") for m in data.get("data", [])]
    print(f"  ✅ {len(ids)} model khả dụng")
    if config.ai_model in ids:
        print(f"  ✅ có model {config.ai_model}")
    else:
        print(f"  ⚠️ không thấy {config.ai_model}. Có các model: {', '.join(map(str, ids[:10]))}")
    return True


def check_sheet() -> bool:
    print("── Sổ ──")
    if config.sheet_backend == "xlsx":
        print(f"  (backend xlsx) {config.root / config.xlsx_path}")
        if config.on_cloud:
            print("  ❌ Backend xlsx KHÔNG dùng được trên cloud (filesystem tạm thời).")
            print("     Đổi SHEET_BACKEND=google.")
    else:
        print(f"  spreadsheet_id: {config.spreadsheet_id or '(trống)'}")
        print(f"  worksheet     : {config.worksheet_name}")
        if config.credentials_json:
            print("  credentials   : từ biến GOOGLE_CREDENTIALS_JSON ✅")
            try:
                info = json.loads(config.credentials_json)
                print(f"  → nhớ Share sheet cho: {info.get('client_email', '(không có)')} (Editor)")
            except json.JSONDecodeError as exc:
                print(f"  ❌ GOOGLE_CREDENTIALS_JSON không phải JSON hợp lệ: {exc}")
        else:
            print(f"  credentials   : file {config.credentials_path()}")
            cred = config.credentials_path()
            if cred.exists():
                try:
                    info = json.loads(cred.read_text(encoding="utf-8"))
                    email = info.get("client_email", "(không có client_email)")
                    print(f"  → nhớ Share sheet cho: {email}  (quyền Editor)")
                except Exception as exc:
                    print(f"  ⚠️ không đọc được file credentials: {exc}")
    try:
        from soho.sheets import build_store

        store = build_store(2)
        rows = store.tail(3)
        print(f"  ✅ {store.info()}")
        print(f"  → {len(rows)} dòng dữ liệu cuối:")
        for row in rows:
            print("    " + " | ".join(str(c) for c in row))
        return True
    except Exception as exc:
        print(f"  ❌ {exc}")
        print("  Gợi ý: nhớ Share sheet cho email service account (quyền Editor).")
        return False


def check_chat_id() -> None:
    print("── ALLOWED_CHAT_ID ──")
    url = f"https://api.telegram.org/bot{config.telegram_token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.load(resp)
    except Exception as exc:
        print(f"  ⚠️ {exc}")
        return
    seen: set[str] = set()
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        user = msg.get("from") or {}
        if chat.get("id"):
            label = f"{chat.get('id')} ({chat.get('type')}, {chat.get('title') or chat.get('first_name') or ''}"
            if user.get("username"):
                label += f", @{user['username']}"
            label += ")"
            seen.add(label)
    if seen:
        print("  Chat đã nhắn bot gần đây:")
        for item in sorted(seen):
            print("   -", item)
        print("  → Copy số chat_id vào ALLOWED_CHAT_ID trong .env")
    else:
        print("  Chưa thấy chat nào. Nhắn /id vào bot trước rồi chạy lại.")


def main() -> int:
    print("=== SoHo AI – kiểm tra setup ===\n")
    env_ok = check_env()
    tg_ok, _ = check_telegram()
    ai_ok = check_ai()
    sheet_ok = check_sheet()
    if tg_ok:
        check_chat_id()
    print("\n=== Kết luận ===")
    ok = env_ok and tg_ok and ai_ok and sheet_ok
    print("✅ Sẵn sàng: python -m soho.bot" if ok else "❌ Còn lỗi ở trên, sửa rồi chạy lại.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
