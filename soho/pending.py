"""Trạng thái chờ xác nhận: bot bóc tin nhắn -> hiện preview -> chờ user bấm nút.

Khoá lưu là `chat_id:message_id` của TIN PREVIEW, không phải chat_id trần.
Lý do: trong group nhiều người dùng cùng lúc. Nếu chỉ khoá theo chat_id thì
preview của người này ghi đè preview của người kia, và bấm nút trên preview
cũ sẽ báo "hết hạn" dù vừa tạo xong.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .ai import Item

TTL_SECONDS = 30 * 60  # 30 phút


def make_key(chat_id: int, message_id: int | None = None) -> str:
    return f"{chat_id}:{message_id}" if message_id else str(chat_id)


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
        if not isinstance(raw, dict):
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

    def _reload_merging(self) -> None:
        """Đọc lại file và GỘP vào RAM.

        Cần thiết khi có 2 process cùng dùng file (hoặc bot vừa restart):
        process này chưa thấy pending do process kia ghi.
        """
        if not self._writable:
            return
        disk = type(self)(self.path)
        for key, pending in disk._data.items():
            if key not in self._data:
                self._data[key] = pending

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

    def put(self, chat_id: int, pending: Pending, message_id: int | None = None) -> str:
        key = make_key(chat_id, message_id)
        pending.message_id = message_id
        # KHÔNG xoá pending khác của cùng chat: trong group mỗi người có preview
        # riêng, xoá sẽ làm bấm nút trên preview của người khác bị "hết hạn".
        # Pending cũ tự hết hạn theo TTL và bị _save() lọc bỏ.
        self._data[key] = pending
        self._save()
        return key

    def get(self, chat_id: int, message_id: int | None = None) -> Pending | None:
        key = make_key(chat_id, message_id)

        # Thử thẳng, rồi thử khoá chat trần (tương thích dữ liệu cũ)
        pending = self._data.get(key)
        if pending is None:
            pending = self._data.get(str(chat_id))

        # Chưa có trong RAM -> có thể process khác vừa ghi; đọc lại file rồi thử lần nữa.
        if pending is None:
            self._reload_merging()
            pending = self._data.get(key) or self._data.get(str(chat_id))

        if pending and pending.expired:
            self._data.pop(key, None)
            self._save()
            return None
        return pending

    def pop(self, chat_id: int, message_id: int | None = None) -> Pending | None:
        key = make_key(chat_id, message_id)
        pending = self.get(chat_id, message_id)
        removed = False
        for k in (key, str(chat_id)):
            if k in self._data:
                del self._data[k]
                removed = True
        if removed:
            self._save()
        return pending

