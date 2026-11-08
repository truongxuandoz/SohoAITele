"""Backup toàn bộ tab 'Thu Chi ' ra file local trước khi test ghi. CHỈ ĐỌC."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHEET_ID = "1yC47kVvWHvHfJARloXxUgf1Aacnf-YxWB8Vy5yBgNdI"
TAB = "Thu Chi "


def main() -> int:
    import gspread
    from google.oauth2.service_account import Credentials

    info = json.loads((ROOT / "credentials" / "service_account.json").read_text(encoding="utf-8"))
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(TAB)

    raw = ws.get_values(range_name="A1:Y1626", value_render_option="UNFORMATTED_VALUE")
    fmt = ws.get_values(range_name="A1:Y1626", value_render_option="FORMATTED_VALUE")
    formulas = ws.get_values(range_name="A1:Y1626", value_render_option="FORMULA")

    out = ROOT / "backup_thu_chi_truoc_test.json"
    out.write_text(
        json.dumps({"raw": raw, "formatted": fmt, "formulas": formulas}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    print(f"Backup: {out}")
    print(f"  {len(raw)} dòng x 25 cột")
    print(f"  R663: {raw[662][:5]}")
    print(f"  R671 (Tổng): {raw[670][:5]}")
    print(f"  R671 formula C: {formulas[670][2] if len(formulas[670]) > 2 else '?'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
