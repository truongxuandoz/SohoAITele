"""Test heartbeat + supervisor — phần giữ bot chạy 24/7."""

from __future__ import annotations

import json
import time

from soho.heartbeat import Heartbeat, read_status


class TestHeartbeat:
    def test_ping_writes_file(self, tmp_path):
        hb = Heartbeat(tmp_path / "status.json")
        hb.ping(sheet_info="OK")
        assert (tmp_path / "status.json").exists()

    def test_counters_and_events(self, tmp_path):
        hb = Heartbeat(tmp_path / "status.json")
        hb.bump("messages_received")
        hb.bump("entries_written", 3)
        hb.event("written", "3 dòng")
        hb.ping()

        data = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
        assert data["counters"]["messages_received"] == 1
        assert data["counters"]["entries_written"] == 3
        assert any(e["kind"] == "written" for e in data["events"])

    def test_unknown_counter_created(self, tmp_path):
        """bump() với key lạ không được crash."""
        hb = Heartbeat(tmp_path / "status.json")
        hb.bump("something_new", 2)
        assert hb.counters["something_new"] == 2

    def test_bump_writes_file_immediately(self, tmp_path):
        """Regression: bump() từng chỉ sửa RAM, không ghi file.

        Hệ quả: bot nhận tin nhưng dashboard vẫn hiện 0 cho tới lần ping
        kế tiếp (tới 30 giây) — trông như bot không nhận được gì.
        """
        path = tmp_path / "status.json"
        hb = Heartbeat(path)
        hb.ping()  # tạo file ban đầu

        hb.bump("messages_received")

        # Không gọi ping() — đọc file ngay phải thấy số mới
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["counters"]["messages_received"] == 1

    def test_event_writes_file_immediately(self, tmp_path):
        """Sự kiện phải hiện trên dashboard ngay, không chờ ping."""
        path = tmp_path / "status.json"
        hb = Heartbeat(path)
        hb.ping()

        hb.event("written", "3 dòng")

        data = json.loads(path.read_text(encoding="utf-8"))
        assert any(e["text"] == "3 dòng" for e in data["events"])

    def test_read_status_alive(self, tmp_path):
        hb = Heartbeat(tmp_path / "status.json")
        hb.ping()
        st = read_status(tmp_path / "status.json")
        assert st["alive"] is True
        assert st["pid"] == hb.pid

    def test_read_status_missing_file(self, tmp_path):
        st = read_status(tmp_path / "khong_ton_tai.json")
        assert st["alive"] is False
        assert "chưa có heartbeat" in st["reason"]

    def test_read_status_stale(self, tmp_path):
        """Heartbeat cũ quá -> báo chết, dù file vẫn còn."""
        hb = Heartbeat(tmp_path / "status.json")
        hb.ping()
        # Làm file cũ đi
        hb.last_update = time.time() - 500
        hb._write()
        st = read_status(tmp_path / "status.json", stale_seconds=45)
        assert st["alive"] is False
        assert "cũ" in st["reason"]

    def test_read_status_corrupt_file(self, tmp_path):
        """File hỏng không được làm dashboard crash."""
        p = tmp_path / "status.json"
        p.write_text("{ khong phai json", encoding="utf-8")
        st = read_status(p)
        assert st["alive"] is False
        assert "không đọc được" in st["reason"]

    def test_unwritable_path_does_not_raise(self, tmp_path):
        """Không ghi được file cũng không được làm chết bot."""
        hb = Heartbeat(tmp_path / "sub" / "dir" / "status.json")
        hb.ping()  # phải tự tạo thư mục

    def test_snapshot_has_required_fields(self, tmp_path):
        hb = Heartbeat(tmp_path / "status.json")
        snap = hb.snapshot()
        for field in ("pid", "started_at", "uptime_seconds", "counters", "events"):
            assert field in snap


class TestSupervisorState:
    def test_initial_state_stopped(self):
        from soho.supervisor import BotSupervisor

        sup = BotSupervisor()
        st = sup.status()
        assert st["status"] == "stopped"
        assert st["alive"] is False
        assert st["pid"] is None

    def test_stop_when_not_running_is_safe(self):
        """stop() khi chưa chạy không được crash."""
        from soho.supervisor import BotSupervisor

        sup = BotSupervisor()
        result = sup.stop()
        assert result["ok"] is True
        assert sup.status()["status"] == "stopped"

    def test_restart_times_window_bounded(self):
        """_restart_times phải có giới hạn để không phình bộ nhớ."""
        from soho.supervisor import MAX_RESTARTS, BotSupervisor

        sup = BotSupervisor()
        assert sup._restart_times.maxlen == MAX_RESTARTS * 2

    def test_status_shape(self):
        """Dashboard dựa vào các key này — đổi tên là vỡ UI."""
        from soho.supervisor import BotSupervisor

        st = BotSupervisor().status()
        for key in ("status", "pid", "alive", "uptime", "restarts", "log_tail"):
            assert key in st


class TestOrphanPrevention:
    """Bot mồ côi sẽ tranh polling với lần chạy sau -> mất tin nhắn.

    Cách chặn: gán bot vào Windows Job Object với KILL_ON_JOB_CLOSE,
    nên dashboard chết (kể cả taskkill /F) là bot chết theo.
    """

    def test_job_object_functions_exist(self):
        from soho import supervisor

        assert callable(supervisor._create_kill_on_close_job)
        assert callable(supervisor._assign_to_job)

    def test_create_job_returns_handle_on_windows(self):
        """Trên Windows phải tạo được job handle."""
        import os

        from soho import supervisor

        handle = supervisor._create_kill_on_close_job()
        if os.name == "nt":
            assert handle, "phải tạo được job object trên Windows"
            # dọn handle
            with contextlib_suppress():
                import ctypes

                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        else:
            assert handle is None

    def test_assign_invalid_pid_returns_false(self):
        """pid rác không được crash, chỉ trả False."""
        from soho import supervisor

        assert supervisor._assign_to_job(None, 999999) is False

    def test_spawn_assigns_to_job(self):
        """_spawn phải gọi _assign_to_job — nếu bị xoá thì mất bảo vệ."""
        import inspect

        from soho import supervisor

        src = inspect.getsource(supervisor.BotSupervisor._spawn)
        assert "_assign_to_job" in src
        assert "_create_kill_on_close_job" in src


def contextlib_suppress():
    import contextlib

    return contextlib.suppress(Exception)


class TestCrashRecoveryLogic:
    def test_proc_cleared_before_restart_delay(self):
        """Regression: từng bug _proc KHÔNG được xoá khi bot chết.

        Hệ quả: vòng lặp thấy `self._proc is not None` -> continue mãi,
        bot không bao giờ được spawn lại, status kẹt ở 'restarting'.
        Kiểm tra: việc gán `self._proc = None` phải nằm TRƯỚC khi tính backoff.
        """
        import inspect

        from soho import supervisor

        src = inspect.getsource(supervisor.BotSupervisor._monitor_loop)
        assert "self._proc = None" in src

        # Thứ tự quan trọng: clear _proc phải xảy ra trước khi tính delay.
        pos_clear = src.index("self._proc = None")
        pos_delay = src.index("delay = BACKOFF")
        assert pos_clear < pos_delay, "_proc phải được xoá trước khi tính backoff"

    def test_spawn_guard_still_present(self):
        """Guard '_proc is not None' vẫn cần để không spawn trùng.

        Tình huống thật: trong lúc chờ backoff, user bấm Start trên dashboard.
        Nếu không có guard, monitor sẽ spawn thêm bot thứ 2 -> tranh polling.
        """
        import inspect

        from soho import supervisor

        src = inspect.getsource(supervisor.BotSupervisor._monitor_loop)
        assert "if self._stop_requested or self._proc is not None" in src
