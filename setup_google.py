"""Kiểm tra file Google service account trước khi dùng.

    python setup_google.py
    python setup_google.py credentials/my-key.json
    python setup_google.py --sheet <SPREADSHEET_ID>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED_FIELDS = ("type", "project_id", "private_key", "client_email", "token_uri")

TICK = "[OK]"
CROSS = "[X]"
WARN = "[!]"


def check_json_shape(info: dict) -> list[str]:
    errors: list[str] = []
    if info.get("type") != "service_account":
        errors.append(f'type phải là "service_account", đang là {info.get("type")!r}')
    for field in REQUIRED_FIELDS:
        if not info.get(field):
            errors.append(f'thiếu field "{field}"')
    key = info.get("private_key") or ""
    if key and not key.startswith("-----BEGIN PRIVATE KEY-----"):
        errors.append("private_key không bắt đầu bằng '-----BEGIN PRIVATE KEY-----'")
    if key and "\\n" in key and "\n" not in key:
        errors.append("private_key có '\\n' literal thay vì xuống dòng thật (JSON bị escape 2 lần)")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Kiểm tra Google service account")
    ap.add_argument("path", nargs="?", default="credentials/service_account.json")
    ap.add_argument("--sheet", help="SPREADSHEET_ID để kiểm tra quyền truy cập")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.is_absolute():
        path = ROOT / path

    print("=== Kiểm tra Google credentials ===\n")

    if not path.exists():
        print(f"{CROSS} Không tìm thấy file: {path}")
        print("\nCách lấy file này:")
        print("  1. console.cloud.google.com -> tạo/chọn project")
        print("  2. APIs & Services -> Library -> bật 'Google Sheets API' VÀ 'Google Drive API'")
        print("  3. APIs & Services -> Credentials -> Create Credentials -> Service account")
        print("  4. Bấm vào service account -> tab Keys -> Add key -> Create new key -> JSON")
        print("  5. Đổi tên file tải về thành service_account.json, đặt vào thư mục credentials/")
        return 1

    print(f"{TICK} Tìm thấy file: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"{CROSS} File không phải JSON hợp lệ: {exc}")
        print("   Có thể bạn tải nhầm file OAuth client hoặc file HTML.")
        return 1

    errors = check_json_shape(info)
    if errors:
        for err in errors:
            print(f"{CROSS} {err}")
        return 1

    email = info["client_email"]
    print(f"{TICK} JSON hợp lệ, là service account")
    print(f"{TICK} project: {info.get('project_id')}")
    print(f"\n{email=}".replace("email=", "   client_email: "))

    # So khớp với .env
    env_file = ROOT / ".env"
    if env_file.exists():
        env_text = env_file.read_text(encoding="utf-8")
        if "GOOGLE_CREDENTIALS_JSON=" in env_text:
            line = next(
                (ln for ln in env_text.splitlines() if ln.startswith("GOOGLE_CREDENTIALS_JSON=")),
                "",
            )
            if line.split("=", 1)[1].strip():
                print(f"{WARN} .env đang set GOOGLE_CREDENTIALS_JSON -> biến này được ưu tiên hơn file.")
                print("   Nếu vừa sửa file mà bot không đổi, kiểm tra lại biến đó.")
        if "SPREADSHEET_ID=" in env_text:
            sid = next(
                (ln.split("=", 1)[1].strip() for ln in env_text.splitlines() if ln.startswith("SPREADSHEET_ID=")),
                "",
            )
            if not sid:
                print(f"\n{WARN} SPREADSHEET_ID trong .env đang trống.")
                print("   Link sheet: https://docs.google.com/spreadsheets/d/<ID_NẰM_Ở_ĐÂY>/edit")
            elif not args.sheet:
                args.sheet = sid

    print("\n=== Bước còn lại (BẮT BUỘC) ===")
    print("  Mở Google Sheet -> Share -> dán email này -> chọn Editor -> Send:")
    print(f"     {email}")
    print("  Nếu chỉ chọn Viewer, bot sẽ lỗi 403 khi ghi.")

    if not args.sheet:
        print("\nChưa có SPREADSHEET_ID nên bỏ qua bước kiểm tra quyền.")
        print("Điền SPREADSHEET_ID vào .env rồi chạy lại với --sheet <id> để kiểm tra.")
        return 0

    print(f"\n=== Kiểm tra quyền truy cập sheet {args.sheet[:12]}... ===")
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        sh = client.open_by_key(args.sheet)
        print(f"{TICK} Mở được sheet: '{sh.title}'")
        print(f"{TICK} Các tab: {', '.join(ws.title for ws in sh.worksheets())}")
    except gspread.exceptions.APIError as exc:
        text = str(exc)
        print(f"{CROSS} Không mở được sheet: {text[:200]}")
        if "403" in text:
            print("\n   403 = chưa share sheet cho service account, hoặc share nhầm quyền Viewer.")
            print(f"   -> Share cho {email} với quyền EDITOR.")
        elif "404" in text:
            print("\n   404 = SPREADSHEET_ID sai, hoặc sheet chưa được share (Google trả 404 thay 403).")
        return 1
    except Exception as exc:
        print(f"{CROSS} Lỗi: {exc}")
        return 1

    print("\n=== Xong. Chạy: python check_setup.py ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
