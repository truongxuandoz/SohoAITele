import pytest
from openpyxl import Workbook, load_workbook

from soho.sheets import XlsxStore


@pytest.fixture()
def ledger(tmp_path):
    """Tạo file Excel giống sổ thật: hàng 1 tiêu đề nhóm, hàng 2 là header cột."""
    path = tmp_path / "soho.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "SoHo"
    ws["A1"] = "A1"
    ws.append([])  # placeholder
    ws.delete_rows(2)
    ws["A2"], ws["B2"], ws["C2"], ws["D2"], ws["E2"] = "Ngày tháng", "Nội Dung", "Thu", "Chi", "ghi chú"
    ws.append(["", "p304 tt", 1_480_000, None, "soho"])
    ws.append(["", "cước hotline", None, 159_000, "soho"])
    ws.append(["11/8", "p304 tt", 990_000, None, "soho"])
    wb.save(path)
    return path


def test_detect_columns(ledger):
    store = XlsxStore(ledger, "SoHo")
    assert store.columns["noi_dung"] == 1
    assert store.columns["thu"] == 2
    assert store.columns["chi"] == 3
    assert store.columns["ghi_chu"] == 4


def test_tail(ledger):
    store = XlsxStore(ledger, "SoHo")
    rows = store.tail(2)
    assert len(rows) == 2
    assert rows[-1][1] == "p304 tt"
    assert rows[-1][0] == "11/8"


def test_append_and_undo(ledger):
    store = XlsxStore(ledger, "SoHo")
    written = store.append([["11/8", "p301 coc 20/8", 500_000, "", "soho"]])
    assert written == [6]

    wb = load_workbook(ledger)
    ws = wb["SoHo"]
    assert ws["B6"].value == "p301 coc 20/8"
    assert ws["C6"].value == 500_000

    store2 = XlsxStore(ledger, "SoHo")
    assert store2.tail(1)[0][1] == "p301 coc 20/8"
    removed = store2.delete_last(1)
    assert removed == 1
    wb = load_workbook(ledger)
    assert wb["SoHo"]["B6"].value is None


def test_append_multiple(ledger):
    store = XlsxStore(ledger, "SoHo")
    written = store.append(
        [
            ["11/8", "suối", "", 10_000, "tm"],
            ["", "102, 202, 302 mibibar", "", 70_000, "tm"],
        ]
    )
    assert written == [6, 7]


class TestColumnDetection:
    """Sổ thật có nhiều kiểu header cho cột nhãn — phải nhận đúng hết."""

    @pytest.mark.parametrize(
        "header_e",
        [
            "ghi chú",      # thường
            " Ghi Chú",     # có dấu cách đầu (sheet T11 thật)
            "Ghi Chú",      # chữ hoa
            "GHI CHU",      # không dấu
            "ghi_chu",      # snake_case
            "note",         # tiếng Anh
            "",             # TRỐNG hoàn toàn
            " ",            # chỉ dấu cách
        ],
    )
    def test_ghi_chu_header_variants(self, tmp_path, header_e):
        """Cột nhãn luôn phải được nhận ra, kể cả khi header trống."""
        wb = Workbook()
        ws = wb.active
        ws.title = "T"
        ws["A2"], ws["B2"], ws["C2"], ws["D2"], ws["E2"] = (
            "Ngày tháng",
            "Nội Dung",
            "Thu",
            "Chi",
            header_e,
        )
        ws.append(["", "p304 tt", 1_000_000, None, "soho"])
        path = tmp_path / "t.xlsx"
        wb.save(path)

        store = XlsxStore(path, "T")
        assert store.columns["ghi_chu"] == 4, f"header={header_e!r}"
        assert store.columns["thu"] == 2
        assert store.columns["chi"] == 3

    def test_all_columns_present(self, tmp_path):
        """Đủ 5 cột chuẩn."""
        wb = Workbook()
        ws = wb.active
        ws.title = "T"
        ws["A2"], ws["B2"], ws["C2"], ws["D2"], ws["E2"] = (
            "Ngày tháng",
            "Nội Dung",
            "Thu",
            "Chi",
            "ghi chú",
        )
        ws.append(["", "x", 100, None, "tm"])
        path = tmp_path / "t.xlsx"
        wb.save(path)
        store = XlsxStore(path, "T")
        assert set(store.columns) >= {"ngay", "noi_dung", "thu", "chi", "ghi_chu"}
