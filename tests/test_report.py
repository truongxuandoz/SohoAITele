"""Test thống kê & hỏi đáp sổ (/xem, /hoi).

Đã đối chiếu với sổ thật: tổng code tính KHỚP 0 đồng so với công thức
=SUM(C314:C658) / =SUM(D314:D658) trong sheet.
"""

from __future__ import annotations

from datetime import date

import pytest

from soho.report import (
    _is_summary_row,
    _parse_vn_date,
    collect_rows,
    format_month_summary,
    looks_like_question,
    month_summary,
)
from soho.sheets import _to_number


class FakeStore:
    """Sổ giả có cùng đặc điểm với sổ thật:

    - Ngày chỉ ghi ở dòng đầu mỗi ngày, dòng sau để trống
    - Có dòng "Tổng" chen giữa
    - Có bút toán chứa chữ "còn lại" (KHÔNG phải dòng tổng)
    """

    header_row = 2
    columns = {"ngay": 0, "noi_dung": 1, "thu": 2, "chi": 3, "ghi_chu": 4}

    def __init__(self, rows):
        self._rows = rows
        self._data_start = 3
        self._data_end = 2 + len(rows)

    def _refresh_bounds(self):
        pass

    def data_region(self):
        return self._data_start, self._data_end

    def read_range(self, start, end):
        """start/end là số dòng 1-based như Google Sheet (dòng 3 = rows[0])."""
        offset = self._data_start
        lo = max(0, start - offset)
        hi = min(len(self._rows), end - offset + 1)
        return self._rows[lo:hi]


# serial date của Google Sheets: 46235 = 2026-08-01
S_AUG1 = 46235
S_AUG2 = 46236


@pytest.fixture
def store():
    return FakeStore(
        [
            [S_AUG1, "mang sang", 1_000_000, "", "tm"],
            ["", "p304 tt", 2_000_000, "", "soho"],
            ["", "suối 10k", "", 10_000, "soho"],
            ["Tổng", "", 3_000_000, 10_000, ""],
            [S_AUG2, "P 101 tt còn lại", 350_000, "", "soho"],
            ["", "cước hotline", "", 167_080, "tk"],
        ]
    )


class TestDateParsing:
    def test_serial_number(self):
        assert _parse_vn_date(S_AUG1) == date(2026, 8, 1)

    def test_serial_as_string(self):
        assert _parse_vn_date("46235") == date(2026, 8, 1)

    def test_dd_mm(self):
        d = _parse_vn_date("13/8")
        assert d.month == 8 and d.day == 13

    def test_dd_mm_yyyy(self):
        assert _parse_vn_date("13/08/2026") == date(2026, 8, 13)

    def test_empty(self):
        assert _parse_vn_date("") is None
        assert _parse_vn_date(None) is None

    def test_garbage(self):
        assert _parse_vn_date("không phải ngày") is None


class TestNumberParsing:
    def test_plain_int(self):
        assert _to_number(1480000) == 1_480_000

    def test_formatted_string(self):
        assert _to_number("1.480.000") == 1_480_000

    def test_comma_string(self):
        assert _to_number("1,480,000") == 1_480_000

    def test_k_suffix(self):
        assert _to_number("159k") == 159_000

    def test_empty(self):
        assert _to_number("") == 0
        assert _to_number(None) == 0

    def test_garbage(self):
        assert _to_number("abc") == 0


class TestSummaryRowDetection:
    def test_tong_in_content(self):
        assert _is_summary_row(["", "Tổng", 123, 456, ""])

    def test_tong_in_col_a(self):
        assert _is_summary_row(["Tổng", "", 123, 456, ""])

    def test_tong_cuoi_thang(self):
        assert _is_summary_row(["", "Tổng cuối tháng7", "", 1287950, ""])

    def test_con_lai_standalone(self):
        assert _is_summary_row(["", "", "Còn lại", 14997173, ""])

    def test_transaction_with_con_lai_is_NOT_summary(self):
        """REGRESSION: 'P 101 tt còn lại' là bút toán thật, không phải dòng tổng.

        Từng bị đánh dấu sai -> mất 350.000 khỏi tổng thu.
        """
        assert not _is_summary_row(["", "P 101 tt còn lại", 350000, "", "soho"])

    def test_transaction_with_tong_inside_is_NOT_summary(self):
        """Bút toán 'thu tổng 3 phòng' cũng không phải dòng tổng."""
        assert not _is_summary_row(["", "thu tổng 3 phòng", 3000000, "", "soho"])

    def test_normal_transaction(self):
        assert not _is_summary_row([S_AUG1, "mang sang", 1000000, "", "tm"])


class TestCollectRows:
    def test_fills_down_date(self, store):
        rows = collect_rows(store, limit=100)
        assert len(rows) == 5  # dòng "Tổng" bị loại
        # 3 dòng đầu cùng ngày 01/08
        assert rows[0]["ngay"] == "2026-08-01"
        assert rows[1]["ngay"] == "2026-08-01"
        assert rows[2]["ngay"] == "2026-08-01"
        # 2 dòng sau ngày 02/08
        assert rows[3]["ngay"] == "2026-08-02"
        assert rows[4]["ngay"] == "2026-08-02"

    def test_summary_row_excluded(self, store):
        rows = collect_rows(store, limit=100)
        assert not any(r["noi_dung"] == "Tổng" for r in rows)

    def test_keeps_amounts(self, store):
        rows = collect_rows(store, limit=100)
        assert sum(r["thu"] for r in rows) == 3_350_000
        assert sum(r["chi"] for r in rows) == 177_080


class TestMonthSummary:
    def test_totals(self, store):
        s = month_summary(store, year=2026, month=8)
        assert s["thu"] == 3_350_000
        assert s["chi"] == 177_080
        assert s["net"] == 3_350_000 - 177_080
        assert s["count"] == 5

    def test_by_tag(self, store):
        s = month_summary(store, year=2026, month=8)
        assert "soho" in s["by_tag"]
        assert s["by_tag"]["soho"]["thu"] == 2_350_000

    def test_empty_month(self, store):
        s = month_summary(store, year=2025, month=1)
        assert s["count"] == 0
        assert s["thu"] == 0

    def test_format_mentions_totals(self, store):
        text = format_month_summary(month_summary(store, year=2026, month=8))
        assert "3.350.000" in text
        assert "177.080" in text

    def test_format_empty_month(self, store):
        text = format_month_summary(month_summary(store, year=2025, month=1))
        assert "Chưa có bút toán" in text


class TestLooksLikeQuestion:
    @pytest.mark.parametrize(
        "text",
        [
            "kiểm tra dòng tiền hiện tại của tháng này",
            "tháng này còn lại bao nhiêu?",
            "xem sổ tháng 8",
            "tổng thu tuần này",
            "báo cáo tháng 8",
            "thống kê chi tiêu",
        ],
    )
    def test_questions_detected(self, text):
        assert looks_like_question(text)

    @pytest.mark.parametrize(
        "text",
        [
            "p304 tt 1.480.000 chi soho",
            "suối 10k",
            "Lương Quỳnh 3.167.000",
        ],
    )
    def test_transactions_not_questions(self, text):
        assert not looks_like_question(text)

    def test_question_mark_always_question(self):
        assert looks_like_question("abc?")
