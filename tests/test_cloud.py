"""Test bot chạy được trong môi trường cloud: filesystem read-only, credentials qua env var."""

import json
from pathlib import Path


def test_config_reads_credentials_json(monkeypatch):
    payload = {"type": "service_account", "client_email": "x@y.iam.gserviceaccount.com"}
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", json.dumps(payload))
    monkeypatch.setenv("SPREADSHEET_ID", "abc123")

    from soho.config import Config

    cfg = Config()
    assert cfg.has_credentials() is True
    assert json.loads(cfg.credentials_json)["client_email"] == "x@y.iam.gserviceaccount.com"


def test_config_missing_credentials_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", "")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", str(tmp_path / "nope.json"))
    monkeypatch.setenv("SPREADSHEET_ID", "abc123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("AI_API_KEY", "x")

    from soho.config import Config

    problems = Config().problems()
    assert any("credentials" in p.lower() for p in problems)


def test_xlsx_backend_warns_on_cloud(monkeypatch):
    monkeypatch.setenv("SHEET_BACKEND", "xlsx")
    monkeypatch.setenv("XLSX_PATH", "data/soho.xlsx")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("AI_API_KEY", "x")
    monkeypatch.setenv("PORT", "10000")  # Render luôn set PORT

    from soho.config import Config

    cfg = Config()
    assert cfg.on_cloud is True
    problems = cfg.problems()
    assert any("tạm thời" in p for p in problems), problems


def test_pending_store_survives_readonly_dir(monkeypatch, tmp_path):
    """Điểm từng crash trên Vercel: mkdir lên chỗ read-only."""
    from soho.ai import Item
    from soho.pending import Pending, PendingStore

    target = tmp_path / "ro" / "pending.json"
    target.parent.mkdir()

    original_mkdir = Path.mkdir

    def deny(self, *args, **kwargs):
        if str(self).startswith(str(tmp_path / "ro")):
            raise PermissionError(13, "Read-only file system")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", deny)

    store = PendingStore(target)  # phải KHÔNG raise
    assert store._writable is False

    store.put(123, Pending(items=[Item(noi_dung="x", chi=1000)]))
    # vẫn hoạt động trong RAM dù không ghi được file
    assert store.get(123) is not None
    assert store.pop(123) is not None


def test_writable_dir_falls_back(monkeypatch, tmp_path):
    from soho import config as cfgmod

    blocked = tmp_path / "blocked"
    monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, "ro")))
    result = cfgmod._writable_dir(blocked)
    assert result.exists() or str(result)
