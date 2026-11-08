"""DRY-RUN với sheet THẬT: chỉ đọc, in ra bot SẼ làm gì. Không ghi gì.

    python dryrun_real.py
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHEET_ID = "1yC47kVvWHvHfJARloXxUgf1Aacnf-YxWB8Vy5yBgNdI"
TAB = "Thu Chi "


def main() -> int:
    from soho.sheets import GoogleSheetStore

    print("=== DRY-RUN: ĐỌC SHEET THẬT, KHÔNG GHI ===\n")

    store = GoogleSheetStore(
        spreadsheet_id=SHEET_ID,
        worksheet_name=TAB,
        credentials_file=ROOT / "credentials" / "service_account.json",
        header_row=2,
    )

    print(f"Sổ: {store.info()}")
    print(f"Cột dò được: {store.columns}")
    print(f"Header: {store.headers}\n")

    start, end = store.data_region()
    print(f"VÙNG DỮ LIỆU THẬT: R{start} .. R{end}")
    print(f"  -> {end - start + 1} dòng dữ liệu\n")

    all_rows = store._all_rows()
    print(f"CÁC DÒNG QUANH ĐIỂM CHÈN (R{max(1, end - 2)}-R{end + 4}):")
    for r in range(max(1, end - 2), min(end + 5, len(all_rows) + 1)):
        row = all_rows[r - 1][:5]
        cells = " | ".join(f"{str(v)[:18]:<18}" for v in row)
        marker = " <<< CHÈN VÀO ĐÂY" if r == end + 1 else ""
        print(f"  R{r:>4}: {cells}{marker}")

    print("\nKIỂM TRA AN TOÀN:")
    # 1) Dòng chèn phải là dòng trống
    next_row = all_rows[end][:5] if end < len(all_rows) else []
    is_empty = not any(str(c).strip() for c in next_row)
    print(f"  [{'OK' if is_empty else 'X'}] R{end + 1} đang trống (nơi chèn)")

    # 2) Khối tổng phải nằm SAU điểm chèn
    totals_after = False
    for r in range(end + 1, min(end + 15, len(all_rows) + 1)):
        row = all_rows[r - 1]
        joined = " ".join(str(c) for c in row[:5]).lower()
        if "tổng" in joined or "còn lại" in joined:
            totals_after = True
            print(f"  [OK] Khối tổng ở R{r} sẽ bị đẩy xuống (không bị ghi đè)")
            break
    if not totals_after:
        print("  [!] Không thấy khối tổng ngay sau vùng dữ liệu")

    # 3) tail() chỉ trả dòng dữ liệu
    tail = store.tail(5)
    print("\n  5 dòng cuối mà bot coi là DỮ LIỆU (dùng làm ngữ cảnh AI):")
    for row in tail:
        print("    " + " | ".join(str(c)[:20] for c in row))

    print("\n=== KHÔNG CÓ GÌ ĐƯỢC GHI. An toàn để chạy thật. ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
