"""Lớp truy cập sổ: Google Sheets (gspread) hoặc file Excel local (openpyxl).

QUAN TRỌNG — thiết kế "an toàn cho sổ thật":
Sổ thu chi thực tế KHÔNG phải bảng phẳng. Nó thường có:
  - khối dữ liệu từng tháng
  - dòng trống ngăn cách
  - khối Tổng / Còn lại / đối soát tiền mặt ở cuối, có công thức

Vì vậy KHÔNG được append vào dòng trống cuối cùng của sheet (sẽ ghi vào giữa
khối đối soát). Thay vào đó phải:
  1. Tìm vùng dữ liệu thật (dừng ở khoảng trống >= GAP_ROWS dòng)
  2. CHÈN dòng mới ngay sau vùng đó, đẩy khối tổng xuống dưới
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Protocol

from .config import config

HEADER_HINTS = {
    "ngay": ("ngay", "ngày", "date"),
    "noi_dung": ("noi dung", "nội dung", "dien giai", "diễn giải", "noi_dung"),
    "thu": ("thu", "thu vao", "thu vào", "income"),
    "chi": ("chi", "chi ra", "expense"),
    "ghi_chu": ("ghi chu", "ghi chú", "note", "ghi_chu"),
}

# Số dòng trống liên tiếp để coi là "hết vùng dữ liệu"
GAP_ROWS = 3


def _norm(text: Any) -> str:
    s = unicodedata.normalize("NFD", str(text or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return " ".join(s.replace("_", " ").lower().split())


def _is_empty_row(row: list[Any], upto: int = 5) -> bool:
    return not any(str(c).strip() for c in row[:upto])


def _to_number(value: Any) -> int:
    """Ép giá trị ô thành số nguyên đồng. Không đọc được -> 0.

    Ô trên sổ có thể là số thật (1480000), hoặc text ("1.480.000", "159k").
    """
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    try:
        return int(float(text.replace(",", "").replace(".", "").replace(" ", "")))
    except ValueError:
        pass
    # Thử các dạng viết tắt tiếng Việt quen thuộc
    try:
        from .money import parse_money

        got = parse_money(text)
        return int(got) if got else 0
    except Exception:
        return 0


class SheetStore(Protocol):
    headers: list[str]

    def tail(self, limit: int = 10) -> list[list[str]]: ...
    def append(self, rows: list[list[Any]]) -> list[int]: ...
    def delete_last(self, count: int) -> int: ...
    def info(self) -> str: ...


class _BaseStore:
    headers: list[str] = []
    header_row: int = 2
    _data_start: int = 0
    _data_end: int = 0

    def _detect_columns(self, header_row: list[Any]) -> dict[str, int]:
        """Tìm index cột theo tên header. Fallback A..E nếu không thấy."""
        found: dict[str, int] = {}
        for idx, cell in enumerate(header_row):
            name = _norm(cell)
            if not name:
                continue
            for key, hints in HEADER_HINTS.items():
                if key in found:
                    continue
                if any(h == name or h in name for h in hints):
                    found[key] = idx
                    break
        if len(found) < 3:
            found = {"ngay": 0, "noi_dung": 1, "thu": 2, "chi": 3, "ghi_chu": 4}

        # Header cột nhãn có thể để TRỐNG hoặc chỉ là dấu cách (sổ T11 như vậy).
        # Nếu tìm được 4 cột chuẩn mà thiếu ghi_chu, và cột kế tiếp tồn tại
        # thì đó chính là cột nhãn — theo đúng thứ tự sổ.
        if "ghi_chu" not in found:
            used = set(found.values())
            for idx in range(len(header_row)):
                if idx not in used:
                    found["ghi_chu"] = idx
                    break
            else:
                found["ghi_chu"] = max(used) + 1 if used else 4

        return found

    def _find_data_bounds(self, rows: list[list[Any]]) -> tuple[int, int]:
        """Trả về (dòng bắt đầu, dòng kết thúc) của VÙNG DỮ LIỆU THẬT.

        Dừng khi gặp GAP_ROWS dòng trống liên tiếp -> phần sau là khối tổng/ghi chú.
        Nếu không có khoảng trống, dùng dòng cuối cùng có dữ liệu.
        """
        start = self.header_row + 1
        end = start
        best_end = start - 1  # vùng rỗng
        gap = 0

        for idx in range(start, len(rows) + 1):
            row = rows[idx - 1] if idx - 1 < len(rows) else []
            if _is_empty_row(row):
                gap += 1
                if gap >= GAP_ROWS:
                    break
            else:
                gap = 0
                best_end = idx

        end = best_end
        return start, end

    def data_region(self) -> tuple[int, int]:
        return self._data_start, self._data_end

    def read_range(self, start_row: int, end_row: int) -> list[list[str]]:
        """Đọc NGUYÊN các dòng trong vùng dữ liệu (1-based, tính cả 2 đầu).

        Dùng cho thống kê/ hỏi đáp: cần đọc nhiều hơn tail() mà vẫn chỉ
        trong vùng dữ liệu thật, không đụng khối Tổng.
        """
        raise NotImplementedError

    def stats(self, limit_rows: int = 1000) -> dict[str, Any]:
        """Tính tổng thu/chi + số dòng. Đi qua read_range của từng backend."""
        self._refresh_bounds() if hasattr(self, "_refresh_bounds") else None
        start, end = self.data_region()
        if end < start:
            return {"rows": 0, "thu": 0, "chi": 0, "start": start, "end": end}

        first = max(start, end - limit_rows + 1)
        rows = self.read_range(first, end)
        cols = self.columns
        thu_i = cols.get("thu", 2)
        chi_i = cols.get("chi", 3)

        total_thu = 0
        total_chi = 0
        counted = 0
        for row in rows:
            t = _to_number(row[thu_i] if thu_i < len(row) else None)
            c = _to_number(row[chi_i] if chi_i < len(row) else None)
            if t:
                total_thu += t
            if c:
                total_chi += c
            if t or c:
                counted += 1
        return {
            "rows": counted,
            "thu": total_thu,
            "chi": total_chi,
            "start": first,
            "end": end,
        }


class XlsxStore(_BaseStore):
    """Backend Excel local: đọc/ghi file .xlsx bằng openpyxl."""

    def __init__(self, path: str | Path, sheet_name: str | None = None, header_row: int = 2):
        from openpyxl import load_workbook

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._wb = load_workbook(self.path)
        self._ws = self._wb[sheet_name] if sheet_name and sheet_name in self._wb.sheetnames else self._wb.active
        self.header_row = header_row
        self.columns = self._detect_columns([c.value for c in self._ws[self.header_row]])
        self.headers = [
            str(self._ws.cell(row=self.header_row, column=i + 1).value or "") for i in range(5)
        ]
        self._refresh_bounds()

    def info(self) -> str:
        return f"Excel: {self.path.name} / sheet '{self._ws.title}'"

    def _all_rows(self) -> list[list[Any]]:
        out = []
        for r in range(1, self._ws.max_row + 1):
            out.append([self._ws.cell(row=r, column=c).value for c in range(1, 6)])
        return out

    def _refresh_bounds(self) -> None:
        self._data_start, self._data_end = self._find_data_bounds(self._all_rows())

    def _row_values(self, row_idx: int) -> list[str]:
        return [
            "" if self._ws.cell(row=row_idx, column=i).value is None else str(self._ws.cell(row=row_idx, column=i).value)
            for i in range(1, 6)
        ]

    def tail(self, limit: int = 10) -> list[list[str]]:
        rows: list[list[str]] = []
        for row_idx in range(self._ws.max_row, self.header_row, -1):
            values = self._row_values(row_idx)
            if any(v.strip() for v in values):
                rows.append(values)
            if len(rows) >= limit:
                break
        return list(reversed(rows))

    def read_range(self, start_row: int, end_row: int) -> list[list[str]]:
        return [self._row_values(r) for r in range(start_row, end_row + 1)]

    def append(self, rows: list[list[Any]]) -> list[int]:
        self._refresh_bounds()
        start = self._data_end + 1
        written: list[int] = []
        if self._data_end > self.header_row:
            # chèn để đẩy khối tổng xuống, giống Google Sheets
            self._ws.insert_rows(start, amount=len(rows))
        for offset, row in enumerate(rows):
            row_idx = start + offset
            for col_idx, value in enumerate(row, start=1):
                self._ws.cell(row=row_idx, column=col_idx).value = value if value != "" else None
            written.append(row_idx)
        self._wb.save(self.path)
        self._refresh_bounds()
        return written

    def delete_last(self, count: int) -> int:
        self._refresh_bounds()
        removed = 0
        for _ in range(count):
            if self._data_end <= self.header_row:
                break
            for col_idx in range(1, 6):
                self._ws.cell(row=self._data_end, column=col_idx).value = None
            self._ws.delete_rows(self._data_end, 1)
            removed += 1
            self._refresh_bounds()
        self._wb.save(self.path)
        return removed


class GoogleSheetStore(_BaseStore):
    """Backend Google Sheets: dùng service account + gspread."""

    def __init__(
        self,
        spreadsheet_id: str,
        worksheet_name: str,
        credentials_file: str | Path,
        header_row: int = 2,
        credentials_json: str = "",
    ):
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        if credentials_json:
            info = json.loads(credentials_json)
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        else:
            creds = Credentials.from_service_account_file(str(credentials_file), scopes=scopes)
        self.client = gspread.authorize(creds)
        self.spreadsheet = self.client.open_by_key(spreadsheet_id)
        # Cho phép tên tab có dấu cách cuối (sổ thật hay bị)
        try:
            self.ws = self.spreadsheet.worksheet(worksheet_name)
        except gspread.WorksheetNotFound:
            self.ws = self._match_tab(worksheet_name)
        self.header_row = header_row
        header_values = self.ws.row_values(header_row) or []
        self.columns = self._detect_columns(header_values)
        self.headers = (header_values + ["", "", "", "", ""])[:5]
        self._refresh_bounds()

    def _match_tab(self, name: str):
        """Tìm tab khớp tên kể cả khi thừa/thiếu dấu cách."""
        want = _norm(name)
        for ws in self.spreadsheet.worksheets():
            if _norm(ws.title) == want:
                return ws
        raise ValueError(
            f"Không thấy tab {name!r}. Các tab có: {[w.title for w in self.spreadsheet.worksheets()]}"
        )

    def info(self) -> str:
        return f"Google Sheet: '{self.spreadsheet.title}' / tab '{self.ws.title}'"

    def _all_rows(self, size: int = 4000) -> list[list[Any]]:
        return self.ws.get_values(
            range_name=f"A1:E{size}", value_render_option="UNFORMATTED_VALUE"
        )

    def _refresh_bounds(self) -> None:
        self._data_start, self._data_end = self._find_data_bounds(self._all_rows())

    def tail(self, limit: int = 10) -> list[list[str]]:
        self._refresh_bounds()
        if self._data_end < self._data_start:
            return []
        start = max(self._data_start, self._data_end - limit + 1)
        rng = f"A{start}:E{self._data_end}"
        rows = self.ws.get_values(range_name=rng)
        return [r + [""] * (5 - len(r)) for r in rows]

    def read_range(self, start_row: int, end_row: int) -> list[list[str]]:
        if end_row < start_row:
            return []
        rows = self.ws.get_values(range_name=f"A{start_row}:E{end_row}")
        return [list(r) + [""] * (5 - len(r)) for r in rows]

    def append(self, rows: list[list[Any]]) -> list[int]:
        self._refresh_bounds()
        start = self._data_end + 1
        n = len(rows)

        # Chèn N dòng ngay sau vùng dữ liệu -> khối Tổng/đối soát bị đẩy xuống,
        # KHÔNG bị ghi đè.
        self.ws.insert_rows(rows, row=start, value_input_option="RAW")

        # Cột A có number format DATE (d/m). Ghi thô sẽ thành text -> ép lại
        # bằng USER_ENTERED để Google parse thành ngày thật.
        date_col = self.columns.get("ngay", 0)
        dates = []
        for row in rows:
            val = str(row[date_col]).strip() if date_col < len(row) else ""
            dates.append([val])
        if any(d[0] for d in dates):
            letter = self._col_letter(date_col)
            self.ws.update(
                range_name=f"{letter}{start}:{letter}{start + n - 1}",
                values=dates,
                value_input_option="USER_ENTERED",
            )

        self._refresh_bounds()
        return list(range(start, start + n))

    def delete_last(self, count: int) -> int:
        self._refresh_bounds()
        removed = 0
        for _ in range(count):
            if self._data_end < self._data_start:
                break
            # gspread.delete_rows(row) -> 1 dòng. KHÔNG truyền end_index:
            # delete_rows(N, N+1) sẽ map thành endIndex=N+1 (0-based exclusive)
            # và XOÁ 2 DÒNG. Chỉ truyền 1 tham số để xoá đúng 1 dòng.
            self.ws.delete_rows(self._data_end)
            removed += 1
            self._refresh_bounds()
        return removed

    @staticmethod
    def _col_letter(index: int) -> str:
        letters = ""
        n = index + 1
        while n:
            n, rem = divmod(n - 1, 26)
            letters = chr(65 + rem) + letters
        return letters


def build_store(header_row: int = 2) -> SheetStore:
    if config.sheet_backend == "google":
        return GoogleSheetStore(
            spreadsheet_id=config.spreadsheet_id,
            worksheet_name=config.worksheet_name,
            credentials_file=config.credentials_path(),
            header_row=header_row,
            credentials_json=config.credentials_json,
        )
    return XlsxStore(config.root / config.xlsx_path, config.worksheet_name, header_row)
