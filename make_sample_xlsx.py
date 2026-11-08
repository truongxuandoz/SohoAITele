"""Tạo file Excel mẫu giống sổ trong ảnh để thử bot: python make_sample_xlsx.py"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROWS = [
    ("", "p304 tt", 1_480_000, None, "soho"),
    ("", "cước hotline", None, 159_000, "soho"),
    ("", "p101 tt", 350_000, None, "soho"),
    ("", "p301 tt", 770_000, None, "soho"),
    ("", "p101+p201 coc 14/8", 500_000, None, "soho"),
    ("", "Biện nhà biệt thự", None, 7_527_967, "soho"),
    ("", "p102+ extrabed", 1_080_000, None, "soho"),
    ("", "quỳnh ứng", None, 500_000, "tm"),
    ("", "kim mua siêu thị cho nhà", None, 734_000, "tm"),
    ("", "Hoàn cọc cho khách", None, 300_000, "soho"),
    ("11/8", "p304 tt", 990_000, None, "soho"),
    ("", "suối", None, 10_000, "tm"),
    ("", "102, 202, 302 mibibar", None, 70_000, "tm"),
    ("", "p301 coc 20/8", 500_000, None, "soho"),
    ("", "p204 102 202 coc 14/8", 2_000_000, None, "soho"),
    ("", "P203 coc 30/8", 500_000, None, "soho"),
    ("", "P102 - 204 coc 13/8", 500_000, None, "soho"),
    ("", "hoan coc", None, 500_000, "soho"),
    ("", "Vu coc p101 13/8", 300_000, None, "soho"),
    ("", "P301 (Thành - hà linh fb ) tt đủ", 1_000_000, None, "kim"),
]


def build(path: Path, sheet_name: str = "SoHo") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    ws["A1"] = "A1"                              # ô formula bar trong ảnh
    ws.merge_cells("B1:E1")
    ws["B1"] = "SỔ THU CHI"
    ws["A2"], ws["B2"], ws["C2"], ws["D2"], ws["E2"] = "Ngày tháng", "Nội Dung", "Thu", "Chi", "ghi chú"

    header_fill = PatternFill("solid", fgColor="1ABC9C")
    for col in "ABCDE":
        cell = ws[f"{col}2"]
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for row in ROWS:
        ws.append(list(row))

    for name, width in (("A", 12), ("B", 34), ("C", 15), ("D", 15), ("E", 12)):
        ws.column_dimensions[name].width = width
    for r in range(3, ws.max_row + 1):
        for c in ("C", "D"):
            ws[f"{c}{r}"].number_format = "#,##0"

    ws.freeze_panes = "A3"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "data" / "soho.xlsx"
    build(out)
    print(f"Đã tạo {out}")
