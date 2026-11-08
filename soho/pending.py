"""Trạng thái chờ xác nhận: bot bóc tin nhắn -> hiện preview -> chờ user bấm nút."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .ai import Item

TTL_SECONDS = 30 * 60  # 30 phút


@dataclass
class Pending:
    items: list[Item]
    note: str = ""
    created_at: float = field(default_factory=time.time)
    message_id: int | None = None

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > TTL_SECONDS


class PendingStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data: dict[str, Pending] = {}
        # Không crash nếu không tạo/ghi được thư mục (filesystem read-only trên cloud).
        # Mất persistence chỉ có nghĩa là pending không sống qua restart — chấp nhận được.
        self._writable = True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._writable = False
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for key, value in raw.items():
            try:
                items = [Item(**it) for it in value.get("items", [])]
            except TypeError:
                continue
            self._data[key] = Pending(
                items=items,
                note=value.get("note", ""),
                created_at=float(value.get("created_at", time.time())),
                message_id=value.get("message_id"),
            )

    def _save(self) -> None:
        if not self._writable:
            return
        payload = {
            key: {
                "items": [vars(it) for it in p.items],
                "note": p.note,
                "created_at": p.created_at,
                "message_id": p.message_id,
            }
            for key, p in self._data.items()
            if not p.expired
        }
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            # Read-only hoặc hết chỗ: giữ state trong RAM, đừng làm sập bot.
            self._writable = False

    def put(self, chat_id: int, pending: Pending) -> None:
        self._data[str(chat_id)] = pending
        self._save()

    def get(self, chat_id: int) -> Pending | None:
        pending = self._data.get(str(chat_id))
        if pending and pending.expired:
            self._data.pop(str(chat_id), None)
            self._save()
            return None
        return pending

    def pop(self, chat_id: int) -> Pending | None:
        pending = self.get(chat_id)
        if str(chat_id) in self._data:
            self._data.pop(str(chat_id), None)
            self._save()
        return pending
