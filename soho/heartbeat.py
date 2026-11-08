"""Ghi trạng thái bot ra file để dashboard đọc được.

Dashboard chạy process riêng, không truy cập được biến trong RAM của bot,
nên phải trao đổi qua file JSON. Ghi bằng atomic replace để dashboard
không bao giờ đọc phải file đang viết dở.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from pathlib import Path
from typing import Any

MAX_EVENTS = 200


class Heartbeat:
    """Bot gọi ping() định kỳ; dashboard đọc snapshot()."""

    def __init__(self, path: Path, started_at: float | None = None):
        self.path = Path(path)
        self.started_at = started_at or time.time()
        self.pid = os.getpid()
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self.counters: dict[str, int] = {
            "messages_received": 0,
            "entries_parsed": 0,
            "entries_written": 0,
            "errors": 0,
            "ai_calls": 0,
        }
        self.last_update: float | None = None
        self.last_message: str | None = None
        self.last_error: str | None = None
        self.sheet_info: str | None = None
        self.bot_username: str | None = None

    def event(self, kind: str, text: str = "") -> None:
        """Ghi một sự kiện vào lịch sử (dùng cho log realtime trên dashboard)."""
        self._events.append({"ts": time.time(), "kind": kind, "text": text})
        self._write()

    def bump(self, key: str, amount: int = 1) -> None:
        """Tăng bộ đếm và ghi file NGAY.

        Phải ghi ngay vì nếu chỉ sửa RAM thì dashboard không thấy số mới
        cho tới lần ping kế tiếp (tới 30 giây) — trông như bot không nhận tin.
        """
        if key in self.counters:
            self.counters[key] += amount
        else:
            self.counters[key] = amount
        self._write()

    def ping(self, **fields: Any) -> None:
        """Cập nhật trạng thái + ghi file. Gọi sau mỗi hoạt động."""
        self.last_update = time.time()
        for key, value in fields.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self._write()

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        return {
            "pid": self.pid,
            "started_at": self.started_at,
            "uptime_seconds": round(now - self.started_at, 1),
            "last_update": self.last_update,
            "seconds_since_update": round(now - self.last_update, 1) if self.last_update else None,
            "alive": True,
            "counters": dict(self.counters),
            "last_message": self.last_message,
            "last_error": self.last_error,
            "sheet_info": self.sheet_info,
            "bot_username": self.bot_username,
            "events": list(self._events)[-60:],
        }

    def _write(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.snapshot(), ensure_ascii=False), encoding="utf-8"
            )
            tmp.replace(self.path)
        except OSError:
            # Không để lỗi ghi log làm chết bot
            pass


def read_status(path: Path, stale_seconds: int = 90) -> dict[str, Any]:
    """Dashboard đọc trạng thái. Trả alive=False nếu file cũ quá."""
    path = Path(path)
    if not path.exists():
        return {"alive": False, "reason": "chưa có heartbeat"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"alive": False, "reason": "không đọc được heartbeat"}

    last = data.get("last_update") or data.get("started_at") or 0
    age = time.time() - last
    data["heartbeat_age"] = round(age, 1)
    data["alive"] = age <= stale_seconds
    if not data["alive"]:
        data["reason"] = f"heartbeat cũ {int(age)}s"
    return data
