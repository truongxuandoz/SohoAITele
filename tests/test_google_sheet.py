"""Test lớp GoogleSheetStore bằng worksheet giả (không cần mạng / credentials)."""

from soho.sheets import GoogleSheetStore


class FakeWorksheet:
    """Bắt chước subset của gspread.Worksheet mà store sử dụng."""

    def __init__(self, grid):
        self.grid = [list(r) for r in grid]
        self.title = "SoHo"
        self.inserted: list[tuple[list[list], int]] = []
        self.updates: list[str] = []
        self.cleared: list[str] = []
        self.deleted: list[int] = []

    def row_values(self, row):
        if row - 1 >= len(self.grid):
            return []
        return [str(c) for c in self.grid[row - 1]]

    @staticmethod
    def _parse_ref(ref: str) -> tuple[int, int]:
        ref = ref.strip()
        letters = "".join(ch for ch in ref if ch.isalpha())
        digits = "".join(ch for ch in ref if ch.isdigit())
        col = 0
        for ch in letters:
            col = col * 26 + (ord(ch.upper()) - 64)
        return int(digits or 1), col

    def get_values(self, range_name=None, value_render_option=None, **kwargs):
        if not range_name:
            r1, c1, r2, c2 = 1, 1, len(self.grid), 5
        else:
            parts = range_name.split(":")
            if len(parts) == 1:
                parts = [parts[0], parts[0]]
            r1, c1 = self._parse_ref(parts[0])
            r2, c2 = self._parse_ref(parts[1])
        out = []
        for r in range(r1, r2 + 1):
            if r - 1 >= len(self.grid):
                break
            row = self.grid[r - 1]
            cells = []
            for c in range(c1, c2 + 1):
                v = row[c - 1] if c - 1 < len(row) else ""
                cells.append("" if v is None else str(v))
            out.append(cells)
        return out

    def insert_rows(self, values, row, value_input_option=None):
        self.inserted.append((values, row))
        for i, new_row in enumerate(values):
            idx = row - 1 + i
            while len(self.grid) < idx:
                self.grid.append([])
            self.grid.insert(idx, list(new_row))
        return {}

    # gspread.Worksheet có các thuộc tính/method này; store dùng để tự mở rộng
    # tab khi sắp hết dòng (_ensure_rows). Fake phải có để test không nổ.
    @property
    def row_count(self):
        return max(len(self.grid), 1000)

    def resize(self, rows=None, cols=None):
        while len(self.grid) < (rows or 0):
            self.grid.append(["", "", "", "", ""])
        return {}

    def update(self, range_name=None, values=None, value_input_option=None, **kwargs):
        self.updates.append(range_name)
        return {}

    def batch_clear(self, ranges):
        self.cleared.extend(ranges)
        return {}

    def delete_rows(self, row, number=None):
        """Bám sát gspread thật:

        delete_rows(start_index, end_index=None) 1-based.
        Nếu end_index None -> end_index = start_index.
        Gửi API: startIndex = start_index - 1, endIndex = end_index  (0-based, exclusive)

        => delete_rows(N)      xoá đúng 1 dòng N
        => delete_rows(N, N+1) xoá 2 dòng: N và N+1  (bug từng gặp!)
        """
        self.deleted.append((row, number))
        start_index = row
        end_index = number if number is not None else start_index
        start0 = start_index - 1
        end0 = end_index
        if end0 < start0:
            raise ValueError(f"endIndex[{end0}] cannot be before startIndex[{start0}]")
        for _ in range(end0 - start0):
            if 0 <= start0 < len(self.grid):
                self.grid.pop(start0)
        return {}


HEADER = ["Ngày tháng", "Nội Dung", "Thu", "Chi", "ghi chú"]


def make_store(grid):
    store = GoogleSheetStore.__new__(GoogleSheetStore)
    store.ws = FakeWorksheet(grid)
    store.spreadsheet = type("SS", (), {"title": "Sổ thu chi"})()
    store.header_row = 2
    header = store.ws.row_values(2)
    store.columns = store._detect_columns(header)
    store.headers = (header + ["", "", "", "", ""])[:5]
    store._refresh_bounds()
    return store


GRID = [
    ["A1"],
    HEADER,
    ["", "p304 tt", "1480000", "", "soho"],
    ["", "cước hotline", "", "159000", "soho"],
]


def test_detect_columns_google():
    store = make_store(GRID)
    assert store.columns["ngay"] == 0
    assert store.columns["noi_dung"] == 1
    assert store.columns["thu"] == 2
    assert store.columns["chi"] == 3
    assert store.columns["ghi_chu"] == 4


def test_bounds_simple():
    store = make_store(GRID)
    assert store.data_region() == (3, 4)


def test_tail_google():
    store = make_store(GRID)
    rows = store.tail(1)
    assert rows == [["", "cước hotline", "", "159000", "soho"]]


def test_append_simple():
    store = make_store(GRID)
    written = store.append([["11/8", "p301 coc 20/8", 500000, "", "soho"]])
    assert written == [5]
    assert store.ws.inserted[0][1] == 5


# ───────────────────── sổ thật: có khối tổng ở cuối ─────────────────────

REAL_GRID = [
    ["A1"],
    HEADER,
    ["1/7", "mang sang", 40331000, "", ""],
    ["", "cước hotline", "", 167080, "tk"],
    ["", "p 203", 1010000, "", "tk"],
    ["", "", "", "", ""],
    ["", "", "", "", ""],
    ["", "", "", "", ""],
    ["", "", "", "", ""],
    ["", "Tổng", "=SUM(C3:C5)", "=SUM(D3:D5)", ""],
    ["", "", "Còn lại", "=C9-D9", ""],
    ["", "LƯU Ý", "", "", ""],
]


def test_bounds_stops_at_gap():
    """Phải dừng ở R5, không nuốt khối Tổng R9..R11."""
    store = make_store(REAL_GRID)
    assert store.data_region() == (3, 5)


def _find_totals_row(grid) -> int:
    for i, row in enumerate(grid):
        if len(row) > 1 and row[1] == "Tổng":
            return i
    return -1


def test_append_inserts_before_totals():
    """Chèn vào R6 -> khối Tổng bị đẩy xuống, không bị ghi đè."""
    store = make_store(REAL_GRID)
    totals_row_before = _find_totals_row(store.ws.grid)
    assert totals_row_before >= 0

    written = store.append([["2/7", "p101 tt", 350000, "", "soho"]])

    assert written == [6]
    values, row = store.ws.inserted[0]
    assert row == 6
    assert values == [["2/7", "p101 tt", 350000, "", "soho"]]

    # khối Tổng vẫn còn, và đã bị đẩy xuống đúng 1 dòng
    totals_row_after = _find_totals_row(store.ws.grid)
    assert totals_row_after == totals_row_before + 1
    assert store.ws.grid[totals_row_after][2] == "=SUM(C3:C5)"


def test_tail_ignores_totals():
    store = make_store(REAL_GRID)
    rows = store.tail(10)
    # vùng dữ liệu là R3..R5 -> đúng 3 dòng, không lẫn khối Tổng
    assert len(rows) == 3
    assert rows[0][1] == "mang sang"
    assert rows[-1][1] == "p 203"
    assert all("Tổng" not in " ".join(str(c) for c in r) for r in rows)


def test_multiple_rows():
    store = make_store(REAL_GRID)
    written = store.append(
        [
            ["2/7", "suối", "", 10000, "tm"],
            ["", "mibibar", "", 70000, "tm"],
        ]
    )
    assert written == [6, 7]


def test_date_column_rewritten_with_user_entered():
    """Cột A là DATE format -> phải ghi lại bằng USER_ENTERED."""
    store = make_store(REAL_GRID)
    store.append([["2/7", "p101 tt", 350000, "", "soho"]])
    assert "A6:A6" in store.ws.updates


def test_delete_last_google():
    store = make_store(REAL_GRID)
    removed = store.delete_last(1)
    assert removed == 1
    # phải gọi delete_rows(N) — 1 tham số, xoá đúng 1 dòng
    assert store.ws.deleted == [(5, None)]


def test_delete_removes_exactly_one_row():
    """Regression 2 lần lỗi thật trên Google Sheets.

    Lần 1: delete_rows(N, 1)  -> API 400 'endIndex[1] cannot be before startIndex[663]'
    Lần 2: delete_rows(N, N+1) -> xoá 2 DÒNG, làm hỏng sổ
    Đúng: delete_rows(N)
    """
    store = make_store(REAL_GRID)
    n_before = len(store.ws.grid)
    store.delete_last(1)
    assert len(store.ws.grid) == n_before - 1, "phải xoá đúng 1 dòng"
    row, arg = store.ws.deleted[0]
    assert arg is None, f"không được truyền end_index (đang truyền {arg})"


def test_delete_last_restores_bounds():
    store = make_store(REAL_GRID)
    before = store.data_region()
    store.append([["2/7", "x", 1000, "", "tm"]])
    assert store.data_region() == (before[0], before[1] + 1)
    store.delete_last(1)
    assert store.data_region() == before


def test_delete_last_empty():
    store = make_store([["A1"], HEADER])
    assert store.delete_last(1) == 0


def test_col_letter():
    store = make_store(GRID)
    assert [store._col_letter(i) for i in range(6)] == ["A", "B", "C", "D", "E", "F"]
    assert store._col_letter(26) == "AA"


def test_tab_name_trailing_space():
    """Sổ thật có tab 'Thu Chi ' (dấu cách cuối)."""
    store = GoogleSheetStore.__new__(GoogleSheetStore)
    store.ws = FakeWorksheet(GRID)
    store.ws.title = "Thu Chi "

    class SS:
        title = "soho boutique"

        def worksheets(self):
            return [store.ws]

    store.spreadsheet = SS()
    matched = store._match_tab("Thu Chi")
    assert matched.title == "Thu Chi "
