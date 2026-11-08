"""Đọc cấu hình từ .env hoặc biến môi trường (Render / Docker / VPS)."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# .env chỉ để dev local; trên cloud biến môi trường đã có sẵn.
load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _get_int_set(name: str) -> set[str]:
    raw = _get(name)
    return {p.strip() for p in raw.replace(";", ",").split(",") if p.strip()}


def _get_bool(name: str) -> bool:
    return _get(name).lower() in ("1", "true", "yes", "on")


def _writable_dir(preferred: Path) -> Path:
    """Trả về thư mục ghi được. Trên Render/Vercel filesystem là read-only,
    chỉ /tmp ghi được — nên phải thử rồi fallback, KHÔNG được crash."""
    for candidate in (preferred, Path(tempfile.gettempdir()) / "soho"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-test"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            return candidate
        except OSError:
            continue
    return Path(tempfile.gettempdir())


@dataclass
class Config:
    telegram_token: str = field(default_factory=lambda: _get("TELEGRAM_BOT_TOKEN"))
    allowed_chats: set[str] = field(default_factory=lambda: _get_int_set("ALLOWED_CHAT_ID"))
    allowed_usernames: set[str] = field(
        default_factory=lambda: {
            u.strip().lstrip("@").lower()
            for u in _get("ALLOWED_USERNAMES").replace(";", ",").split(",")
            if u.strip()
        }
    )

    sheet_backend: str = field(default_factory=lambda: (_get("SHEET_BACKEND", "google") or "google").lower())
    spreadsheet_id: str = field(default_factory=lambda: _get("SPREADSHEET_ID"))
    worksheet_name: str = field(default_factory=lambda: _get("WORKSHEET_NAME", "Sheet1") or "Sheet1")
    credentials_file: str = field(
        default_factory=lambda: _get("GOOGLE_CREDENTIALS_FILE", "credentials/service_account.json")
    )
    # Trên Render: dán NGUYÊN nội dung file JSON vào biến này (không cần upload file).
    credentials_json: str = field(default_factory=lambda: _get("GOOGLE_CREDENTIALS_JSON"))
    xlsx_path: str = field(default_factory=lambda: _get("XLSX_PATH", "data/soho.xlsx"))

    ai_base_url: str = field(
        default_factory=lambda: _get("AI_BASE_URL", "https://api.hermesgate.app/v1").rstrip("/")
        or "https://api.hermesgate.app/v1"
    )
    ai_api_key: str = field(default_factory=lambda: _get("AI_API_KEY"))
    ai_model: str = field(default_factory=lambda: _get("AI_MODEL", "gemini-3.8-flash-high"))
    ai_timeout: int = field(default_factory=lambda: int(_get("AI_TIMEOUT", "60") or 60))

    timezone: str = field(default_factory=lambda: _get("TIMEZONE", "Asia/Ho_Chi_Minh"))
    max_items: int = field(default_factory=lambda: int(_get("MAX_ITEMS", "20") or 20))

    # Webhook (cho Render / Vercel / VPS có HTTPS). Bỏ trống -> dùng polling.
    webhook_url: str = field(default_factory=lambda: _get("WEBHOOK_URL"))
    webhook_secret: str = field(default_factory=lambda: _get("WEBHOOK_SECRET"))
    port: int = field(default_factory=lambda: int(_get("PORT", "0") or 0))
    enable_health_server: bool = field(default_factory=lambda: _get_bool("ENABLE_HEALTH_SERVER"))

    root: Path = ROOT

    @property
    def on_cloud(self) -> bool:
        """Nhận diện môi trường PaaS (Render đặt RENDER=true)."""
        return _get_bool("RENDER") or bool(self.port)

    def credentials_path(self) -> Path:
        p = Path(self.credentials_file)
        return p if p.is_absolute() else (self.root / p)

    def has_credentials(self) -> bool:
        return bool(self.credentials_json) or self.credentials_path().exists()

    def data_dir(self) -> Path:
        """Thư mục ghi được cho state (pending.json)."""
        return _writable_dir(self.root / "data")

    def problems(self) -> list[str]:
        issues: list[str] = []
        if not self.telegram_token:
            issues.append("Thiếu TELEGRAM_BOT_TOKEN (lấy từ @BotFather).")
        if not self.ai_api_key:
            issues.append("Thiếu AI_API_KEY (gateway OpenAI-compatible).")
        if not self.ai_base_url:
            issues.append("Thiếu AI_BASE_URL.")
        if self.sheet_backend == "google":
            if not self.spreadsheet_id:
                issues.append("Thiếu SPREADSHEET_ID (phần giữa /d/ và /edit của link sheet).")
            if not self.has_credentials():
                issues.append(
                    "Không thấy credentials: đặt GOOGLE_CREDENTIALS_JSON (nội dung JSON) "
                    f"hoặc file {self.credentials_path()}"
                )
        elif self.sheet_backend == "xlsx":
            if not self.xlsx_path:
                issues.append("Thiếu XLSX_PATH cho backend xlsx.")
            if self.on_cloud:
                issues.append(
                    "Backend 'xlsx' KHÔNG dùng được trên cloud: filesystem là tạm thời, "
                    "file sẽ mất sau mỗi lần deploy/restart. Đổi SHEET_BACKEND=google."
                )
        else:
            issues.append("SHEET_BACKEND chỉ nhận 'google' hoặc 'xlsx'.")
        return issues


config = Config()
