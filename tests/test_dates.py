"""Test quy tắc NGÀY THÁNG.

Hai yêu cầu thật của user:
  1. "ứng với mỗi 1 ngày trên cột ngày tháng thì chỉ có 1 lần nhập ngày thôi"
     -> sổ đã bị lặp: R69/R75/R77 đều ghi 8/11 trong khi chỉ dòng đầu được có
  2. "kiểm tra ngược lại xem có note ngày cho cột vào ngày đấy chưa,
      nếu chưa thì thêm vào"
     -> nếu ngày user nói CHƯA có trong sổ thì phải ghi vào cột A,
        không được để trống (trống = thuộc ngày dòng trên -> SAI ngày)
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from soho.ai import Item
from soho.dates import (
    date_exists_in_sheet,
    ensure_date_present,
    parse_relative_date,
)
from soho.sheets import GoogleSheetStore

HEADER = ["Ngày tháng", "Nội Dung", "Thu", "Chi", " Ghi Chú"]
S_8 = 46334  # 2026-11-08
S_7 = 46333  # 2026-11-07


class WS:
    def __init__(self, grid):
        self.grid = [list(r) for r in grid]
        self.title = "T11"

    @property
    def row_count(self):
        return 1000

    def row_values(self, row):
        return [str(c) for c in self.grid[row - 1]] if row - 1 < len(self.grid) else []

    def get_values(self, range_name=None, value_render_option=None, **kw):
        import re

        m = re.match(r"A(\d+):E(\d+)", range_name or "")
        r1, r2 = (int(m.group(1)), int(m.group(2))) if m else (1, len(self.grid))
        out = []
        for r in range(r1, r2 + 1):
            if r - 1 >= len(self.grid):
                break
            row = self.grid[r - 1]
            out.append(["" if c is None else str(c) for c in (row + [""] * 5)[:5]])
        return out

    def insert_rows(self, values, row, value_input_option=None):
        for i, nr in enumerate(values):
            self.grid.insert(row - 1 + i, list(nr))
        return {}

    def update(self, range_name=None, values=None, value_input_option=None, **kw):
        import re

        m = re.match(r"A(\d+):E(\d+)", range_name or "")
        if m and values:
            r1 = int(m.group(1))
            for i, nr in enumerate(values):
                while len(self.grid) <= r1 - 1 + i:
                    self.grid.append(["", "", "", "", ""])
                self.grid[r1 - 1 + i] = list(nr) + [""] * (5 - len(nr))
        return {}


def make_store(grid):
    st = GoogleSheetStore.__new__(GoogleSheetStore)
    st.ws = WS(grid)
    st.spreadsheet = type("SS", (), {"title": "kho soho"})()
    st.header_row = 2
    hdr = st.ws.row_values(2)
    st.columns = st._detect_columns(hdr)
    st.headers = (hdr + [""] * 5)[:5]
    st._refresh_bounds()
    return st


def grid_with_8nov():
    g = [["", "", "", "", ""], HEADER]
    g.append([S_7, "p301 tt", 670000, "", "vân"])       # R3: 7/11
    g.append(["", "p102 pt", 10000, "", "vân"])         # R4
    g.append([S_8, "P304 tt checkout trễ", "", 70000, "vân"])  # R5: 8/11
    g.append(["", "P304 tt 1 snack", "", 15000, "vân"]) # R6
    for _ in range(5):
        g.append(["", "", "", "", ""])
    g.append(["", "Tồng thu chi", 999, 888, ""])
    return g


# ────────────────────── 1. mỗi ngày chỉ ghi 1 lần ──────────────────────


class TestOneDatePerDay:
    def test_prepare_keeps_only_first_date(self):
        """Lô 3 dòng cùng 9/11 (ngày CHƯA có trong sổ) -> chỉ dòng đầu mang ngày."""
        store = make_store(grid_with_8nov())
        rows = [
            ["9/11", "P304 tt checkout trễ", "", 70000, "vân"],
            ["9/11", "P304 tt 1 snack", "", 15000, "vân"],
            ["9/11", "P203, 302, tt đủ", 960000, "", "soho"],
        ]
        out = store._prepare_rows(rows)
        assert out[0][0] == "9/11", "dòng đầu phải giữ ngày"
        assert out[1][0] == "", "dòng 2 cùng ngày -> bỏ trống"
        assert out[2][0] == ""

    def test_date_already_in_sheet_is_not_repeated(self):
        """8/11 đã có ở R5 -> bút toán mới ngày 8/11 không được ghi lại."""
        store = make_store(grid_with_8nov())
        rows = [["8/11", "mới", 1000, "", "tm"]]
        out = store._prepare_rows(rows)
        assert out[0][0] == "", "ngày đã có trong sổ -> không ghi lặp"

    def test_new_date_is_written(self):
        """Ngày 9/11 chưa có -> phải ghi vào cột A."""
        store = make_store(grid_with_8nov())
        rows = [["9/11", "mới", 1000, "", "tm"]]
        out = store._prepare_rows(rows)
        assert out[0][0] == "9/11", "ngày mới phải được ghi"

    def test_mixed_dates_in_one_batch(self):
        """Một lô có 2 ngày -> mỗi ngày ghi 1 lần."""
        store = make_store(grid_with_8nov())
        rows = [
            ["9/11", "a", 1000, "", "tm"],
            ["9/11", "b", 2000, "", "tm"],
            ["10/11", "c", 3000, "", "tm"],
            ["10/11", "d", 4000, "", "tm"],
        ]
        out = store._prepare_rows(rows)
        assert [r[0] for r in out] == ["9/11", "", "10/11", ""]

    def test_append_actually_writes_blank_for_same_day(self):
        """Kiểm tra end-to-end qua append(): cột A chỉ có 1 ngày."""
        store = make_store(grid_with_8nov())
        store.append(
            [
                ["8/11", "x1", "", 1000, "tm"],
                ["8/11", "x2", "", 2000, "tm"],
            ]
        )
        # 2 dòng mới nằm ngay sau vùng dữ liệu cũ
        got = [store.ws.grid[5], store.ws.grid[6]]
        assert got[0][0] == "", "8/11 đã có trong sổ"
        assert got[1][0] == ""

    def test_no_date_stays_blank(self):
        store = make_store(grid_with_8nov())
        rows = [["", "không ngày", 1000, "", "tm"]]
        out = store._prepare_rows(rows)
        assert out[0][0] == ""

    def test_date_key_handles_all_formats(self):
        for val in (S_8, "46334", "8/11", "08/11/2026", "2026-11-08"):
            assert GoogleSheetStore._date_key(val) == "2026-11-08", f"val={val!r}"

    def test_date_key_rejects_garbage(self):
        for val in ("", None, "linh tinh", 0, "p304"):
            assert GoogleSheetStore._date_key(val) == "", f"val={val!r}"


# ────────────────────── 2. kiểm tra ngược ──────────────────────


class TestReverseDateCheck:
    def test_finds_existing_date(self):
        store = make_store(grid_with_8nov())
        exists, row = date_exists_in_sheet(store, date(2026, 11, 8))
        assert exists is True
        assert row == 5

    def test_reports_missing_date(self):
        store = make_store(grid_with_8nov())
        exists, row = date_exists_in_sheet(store, date(2026, 11, 9))
        assert exists is False
        assert row is None

    def test_finds_7nov(self):
        store = make_store(grid_with_8nov())
        exists, row = date_exists_in_sheet(store, date(2026, 11, 7))
        assert exists is True
        assert row == 3

    def test_ensure_adds_date_when_missing(self):
        """User ghi '9/11 ...' mà sổ chưa có 9/11 -> phải ghi vào cột A."""
        store = make_store(grid_with_8nov())
        items = [Item(noi_dung="p304", chi=5000)]
        notes = ensure_date_present(items, store, "9/11 p304 tt 500k")
        assert items[0].ngay_thang, "phải được bổ sung ngày"
        assert any("chưa có trong sổ" in n for n in notes)

    def test_ensure_notes_when_date_exists(self):
        """Sổ đã có 8/11 -> nói rõ là để trống đúng."""
        store = make_store(grid_with_8nov())
        items = [Item(noi_dung="x", chi=1000, ngay_thang="8/11")]
        notes = ensure_date_present(items, store, "8/11 x 1000")
        assert any("đã có trong sổ" in n for n in notes)

    def test_ensure_keeps_user_date(self):
        store = make_store(grid_with_8nov())
        items = [Item(noi_dung="x", chi=1000, ngay_thang="9/11")]
        ensure_date_present(items, store, "")
        assert items[0].ngay_thang == "9/11"

    def test_ensure_clears_duplicate_in_batch(self):
        """Nhiều dòng cùng ngày -> chỉ dòng đầu mang ngày."""
        store = make_store(grid_with_8nov())
        items = [
            Item(noi_dung="a", chi=1000, ngay_thang="9/11"),
            Item(noi_dung="b", chi=2000, ngay_thang="9/11"),
        ]
        ensure_date_present(items, store, "")
        assert items[0].ngay_thang == "9/11"
        assert items[1].ngay_thang == ""

    def test_ensure_uses_relative_date(self):
        """'hôm qua' -> dùng ngày thật."""
        store = make_store(grid_with_8nov())
        items = [Item(noi_dung="x", chi=1000)]
        ensure_date_present(items, store, "hôm qua x 1000")
        yesterday = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")
        assert items[0].ngay_thang == yesterday

    def test_ensure_no_date_no_crash(self):
        """Không có ngày nào -> không crash, không thêm gì."""
        store = make_store(grid_with_8nov())
        items = [Item(noi_dung="x", chi=1000)]
        ensure_date_present(items, store, "x 1000")
        assert items[0].ngay_thang == ""


class TestRelativeDates:
    @pytest.mark.parametrize(
        "text,delta",
        [
            ("hôm nay", 0),
            ("hom nay", 0),
            ("hôm qua", 1),
            ("hom qua", 1),
            ("hôm kia", 2),
            ("2 ngày trước", 2),
            ("3 ngay truoc", 3),
        ],
    )
    def test_relative(self, text, delta):
        assert parse_relative_date(text) == date.today() - timedelta(days=delta)

    def test_tomorrow(self):
        assert parse_relative_date("mai") == date.today() + timedelta(days=1)

    def test_no_relative(self):
        assert parse_relative_date("p304 tt 500k") is None
