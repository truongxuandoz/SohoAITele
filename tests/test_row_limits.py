"""Test CHỐNG GHI ĐÈ KHỐI TỔNG khi vùng dữ liệu lan xuống.

Câu hỏi thật: "giả sử điền kín từ dòng 79 thì dòng 80 đang có data nó sẽ xử lý sao"

Trả lời: phải dừng ở dòng cuối dữ liệu thật (R74), KHÔNG được coi dòng
Tổng (R80) là dữ liệu. Nếu sai, bot sẽ chèn dòng mới vào giữa khối
Tổng/đối soát hoặc ghi đè lên đó.

Trước khi sửa: gap < GAP_ROWS -> vùng dữ liệu nuốt khối Tổng.
Sau khi sửa: dùng dòng Tổng làm MỐC CỨNG -> an toàn ở mọi gap, kể cả gap=0.
"""

from __future__ import annotations

import pytest

from soho.sheets import GAP_ROWS, GoogleSheetStore

HEADER = ["Ngày tháng", "Nội Dung", "Thu", "Chi", " Ghi Chú"]


class FakeWS:
    def __init__(self, grid):
        self.grid = [list(r) for r in grid]
        self.title = "T11"
        self.inserted = []
        self.updates = []
        self.deleted = []

    @property
    def row_count(self):
        return max(len(self.grid), 1000)

    def resize(self, rows=None, cols=None):
        while len(self.grid) < (rows or 0):
            self.grid.append(["", "", "", "", ""])
        return {}

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
            out.append(["" if (c is None) else str(c) for c in (row + [""] * 5)[:5]])
        return out

    def insert_rows(self, values, row, value_input_option=None):
        self.inserted.append((list(values), row))
        for i, nr in enumerate(values):
            self.grid.insert(row - 1 + i, list(nr))
        return {}

    def update(self, range_name=None, values=None, value_input_option=None, **kw):
        self.updates.append(range_name)
        import re

        m = re.match(r"A(\d+):E(\d+)", range_name or "")
        if m and values:
            r1 = int(m.group(1))
            for i, nr in enumerate(values):
                while len(self.grid) <= r1 - 1 + i:
                    self.grid.append(["", "", "", "", ""])
                self.grid[r1 - 1 + i] = list(nr) + [""] * (5 - len(nr))
        return {}

    def delete_rows(self, row, number=None):
        self.deleted.append(row)
        for _ in range(number or 1):
            if row - 1 < len(self.grid):
                self.grid.pop(row - 1)
        return {}


def build(n_data: int, gap: int, extra_tail: int = 6) -> list[list]:
    rows = [["", "", "", "", ""], HEADER]
    for i in range(1, n_data + 1):
        rows.append(["", f"p30{i} tt", 100_000 * i, "", "soho"])
    for _ in range(gap):
        rows.append(["", "", "", "", ""])
    rows.append(["", "Tồng thu chi", 999_999, 888_888, ""])
    rows.append(["", "", "mang sang", "soho", 44_891_978])
    rows.append(["", "", "", "Kim", 23_439_203])
    rows.append(["", "", "", "tm", 5_000_000])
    rows.append(["", "", "", "Tổng tiền", 39_627_486])
    for _ in range(extra_tail):
        rows.append(["", "", "", "", ""])
    return rows


def make_store(grid):
    store = GoogleSheetStore.__new__(GoogleSheetStore)
    store.ws = FakeWS(grid)
    store.spreadsheet = type("SS", (), {"title": "kho soho"})()
    store.header_row = 2
    hdr = store.ws.row_values(2)
    store.columns = store._detect_columns(hdr)
    store.headers = (hdr + [""] * 5)[:5]
    store._refresh_bounds()
    return store


N = 72  # so dong du lieu, giong so that


class TestGapShrinking:
    """Bí danh câu hỏi: nếu các dòng trống bị lấp, có ghi đè Tổng không?"""

    @pytest.mark.parametrize("gap", [5, 4, 3, 2, 1, 0])
    def test_data_end_never_reaches_total(self, gap):
        """Dù gap = 0, vùng dữ liệu phải dừng ở R(2+N)."""
        store = make_store(build(N, gap))
        start, end = store.data_region()
        total_row = 2 + N + gap + 1

        assert start == 3
        assert end == 2 + N, (
            f"gap={gap}: vùng dữ liệu kết thúc ở R{end}, "
            f"phải là R{2 + N} (khối Tổng ở R{total_row})"
        )
        assert end < total_row, f"gap={gap}: vùng dữ liệu đã lấn vào khối Tổng!"

    @pytest.mark.parametrize("gap", [2, 1, 0])
    def test_append_goes_before_total_even_when_tight(self, gap):
        """Chèn dòng mới phải nằm TRƯỚC khối Tổng, không đè lên."""
        store = make_store(build(N, gap))
        before = [list(r) for r in store.ws.grid]
        total_row = 2 + N + gap + 1
        total_content = before[total_row - 1][1]

        store.append([["9/11", "MỚI", 1000, "", "test"]])

        # Dòng Tổng phải bị đẩy xuống 1, nội dung còn nguyên
        assert store.ws.grid[total_row][1] == total_content, "khối Tổng bị ghi đè!"

    def test_total_row_found_with_unicode_o(self):
        """Sổ ghi 'Tồng' (dấu ồ) — không được so sánh chuỗi thô."""
        store = make_store(build(N, 3))
        tr = store._find_total_row(store.ws.grid, 3)
        assert tr == 2 + N + 3 + 1, f"phải tìm ra dòng Tổng, được {tr}"

    def test_mang_sang_at_top_is_data_not_total(self):
        """'mang sang' ở dòng đầu sổ là BÚT TOÁN THẬT, không phải khối tổng."""
        rows = [["", "", "", "", ""], HEADER, ["1/7", "mang sang", 40_331_000, "", "tm"]]
        rows += [["", f"p{i} tt", 1000, "", "tm"] for i in range(30)]
        store = make_store(rows)
        start, end = store.data_region()
        assert start == 3
        assert end == len(rows), "dòng 'mang sang' đầu sổ không được cắt vùng dữ liệu"

    def test_content_with_tong_inside_is_data(self):
        """'thu tổng 3 phòng' là bút toán, không phải dòng tổng."""
        rows = [["", "", "", "", ""], HEADER]
        rows += [["", f"p{i} tt", 1000, "", "soho"] for i in range(30)]
        rows.append(["", "thu tổng 3 phòng", 3_000_000, "", "soho"])
        rows += [["", "", "", "", ""]] * 5
        rows.append(["", "Tồng thu chi", 1, 2, ""])
        store = make_store(rows)
        _start, end = store.data_region()
        assert end == 33, f"dòng 'thu tổng 3 phòng' phải được tính là dữ liệu (end={end})"


class TestRowLimitGuards:
    """Khi tab sắp hết dòng, phải tự mở rộng thay vì để Google báo lỗi."""

    def test_ensure_rows_grows_worksheet(self):
        store = make_store(build(N, 5))
        store.ws.grid = store.ws.grid[: store._data_end + 1]  # cắt sát đáy
        store._ensure_rows(3)
        assert store.ws.row_count >= store._data_end + 3

    def test_append_does_not_crash_near_limit(self):
        store = make_store(build(N, 5))
        store.ws.grid = store.ws.grid[: store._data_end]
        written = store.append([["9/11", "x", 1000, "", "t"]])
        assert written

    def test_raises_when_at_hard_limit(self, monkeypatch):
        """Chạm giới hạn cứng thì báo lỗi RÕ RÀNG, không lỗi API khó hiểu."""
        from soho import sheets as sh

        monkeypatch.setattr(sh, "MAX_SHEET_ROWS", 100)
        store = make_store(build(N, 5))
        with pytest.raises(RuntimeError, match="giới hạn"):
            store._ensure_rows(3)


class TestGapConstantStillMatters:
    def test_gap_rows_used_when_no_total_row(self):
        """Không có khối Tổng -> vẫn dừng theo GAP_ROWS."""
        rows = [["", "", "", "", ""], HEADER]
        rows += [["", f"p{i}", 1000, "", "tm"] for i in range(10)]
        rows += [["", "", "", "", ""]] * (GAP_ROWS + 2)
        rows += [["", "sau khoang trong", 5000, "", "tm"]]
        store = make_store(rows)
        _start, end = store.data_region()
        assert end == 12, "phải dừng ở dòng cuối trước khoảng trống"
