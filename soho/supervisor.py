"""Supervisor: quản lý process bot như một dịch vụ.

Vì sao cần: bot polling phải chạy 24/7. Process có thể chết vì mất mạng,
hết RAM, hoặc lỗi code. Supervisor giám sát và tự khởi động lại, đồng thời
cho dashboard start/stop/restart mà không cần mở terminal.

Chạy như module: python -m soho.supervisor
Hoặc qua dashboard: soho/dashboard.py gọi vào đây.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

log = logging.getLogger("supervisor")

MAX_RESTARTS = 20          # trong RESTART_WINDOW giây
RESTART_WINDOW = 300       # 5 phút
BACKOFF = [2, 5, 10, 20, 30, 60]  # giây giữa các lần restart
HEALTHY_UPTIME = 60        # chạy quá 60s thì coi là ổn định, reset backoff


@dataclass
class BotState:
    status: str = "stopped"          # stopped | starting | running | crashed | restarting
    pid: int | None = None
    started_at: float | None = None
    restarts: int = 0
    last_exit_code: int | None = None
    last_exit_at: float | None = None
    last_error: str | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=500))

    @property
    def uptime(self) -> float:
        return round(time.time() - self.started_at, 1) if self.started_at else 0.0


# ── Windows Job Object: giết bot khi dashboard chết ──────────────────
# Không dùng cách này thì đóng cửa sổ dashboard (nhất là kill cứng) để lại
# bot mồ côi, và bot mồ côi sẽ tranh polling với lần chạy sau -> tin nhắn
# mất ngẫu nhiên. Job object là cơ chế của OS nên kill cứng vẫn sạch.

_JOB_HANDLE = None


def _create_kill_on_close_job():
    """Tạo job object tự giết con khi handle đóng (tức khi dashboard chết)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        JobObjectExtendedLimitInformation = 9
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception:  # pragma: no cover - chỉ chạy trên Windows
        return None


def _assign_to_job(handle, pid: int) -> bool:
    """Gán process vào job. Trả False nếu không gán được."""
    if os.name != "nt" or handle is None:
        return False
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_SET_QUOTA = 0x0100
        PROCESS_TERMINATE = 0x0001
        kernel32.OpenProcess.restype = ctypes.c_void_p
        proc = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not proc:
            return False
        try:
            return bool(kernel32.AssignProcessToJobObject(handle, ctypes.c_void_p(proc)))
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(proc))
    except Exception:  # pragma: no cover
        return False


class BotSupervisor:
    """Quản lý 1 process bot. Thread-safe cho FastAPI gọi từ nhiều request."""

    def __init__(self) -> None:
        self.state = BotState()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._reader: threading.Thread | None = None
        self._monitor: threading.Thread | None = None
        self._stop_requested = False
        self._restart_times: deque[float] = deque(maxlen=MAX_RESTARTS * 2)

    # ────────────────────────── public API ──────────────────────────

    def start(self) -> dict:
        with self._lock:
            if self._is_alive():
                return {"ok": False, "reason": "bot đang chạy rồi", "pid": self.state.pid}
            self._stop_requested = False
            self._spawn()
            self._ensure_monitor()
            return {"ok": True, "pid": self.state.pid}

    def stop(self, timeout: float = 10.0) -> dict:
        with self._lock:
            self._stop_requested = True
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self.state.status = "stopped"
                self.state.pid = None
                return {"ok": True, "reason": "bot đã tắt"}

            log.info("Dừng bot pid=%s", proc.pid)
            try:
                proc.terminate()
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log.warning("Bot không dừng sau %.0fs, kill cứng", timeout)
                proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=5)
            except Exception as exc:
                log.error("Lỗi khi dừng: %s", exc)

            self._proc = None
            self.state.status = "stopped"
            self.state.pid = None
            self.state.started_at = None
            return {"ok": True}

    def restart(self) -> dict:
        self.stop()
        time.sleep(1.0)
        return self.start()

    def status(self) -> dict:
        with self._lock:
            alive = self._is_alive()
            if alive and self.state.status != "running":
                self.state.status = "running"
            if not alive and self.state.status == "running":
                self.state.status = "crashed"
            return {
                "status": self.state.status,
                "pid": self.state.pid,
                "alive": alive,
                "uptime": self.state.uptime,
                "restarts": self.state.restarts,
                "last_exit_code": self.state.last_exit_code,
                "last_error": self.state.last_error,
                "log_tail": list(self.state.logs)[-80:],
            }

    def logs(self, limit: int = 200) -> list[str]:
        return list(self.state.logs)[-limit:]

    # ────────────────────────── internals ──────────────────────────

    def _is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _python_exe(self) -> str:
        return str(PYTHON) if PYTHON.exists() else sys.executable

    def _spawn(self) -> None:
        global _JOB_HANDLE
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        # Xoá heartbeat cũ: nếu không, dashboard sẽ thấy heartbeat của lần chạy
        # trước và tưởng bot còn sống trong lúc bot mới đang khởi động.
        with contextlib.suppress(OSError):
            (LOG_DIR / "status.json").unlink(missing_ok=True)

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self.state.status = "starting"
        self._proc = subprocess.Popen(
            [self._python_exe(), "-m", "soho.bot"],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
        self.state.pid = self._proc.pid

        # Gán vào job object để bot chết theo khi dashboard chết (kể cả kill cứng).
        if _JOB_HANDLE is None:
            _JOB_HANDLE = _create_kill_on_close_job()
        if _JOB_HANDLE and not _assign_to_job(_JOB_HANDLE, self._proc.pid):
            log.warning(
                "Không gán được job object (pid có thể đã nằm trong job khác). "
                "Bot sẽ không tự chết theo dashboard."
            )

        self.state.started_at = time.time()
        self.state.status = "running"
        log.info("Khởi động bot pid=%s", self._proc.pid)
        self.state.logs.append(f"--- started pid {self._proc.pid} ---")

        self._reader = threading.Thread(target=self._read_logs, args=(self._proc,), daemon=True)
        self._reader.start()

    def _read_logs(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.state.logs.append(line)
                    if "ERROR" in line or "Traceback" in line:
                        self.state.last_error = line[:300]
        except Exception as exc:  # pragma: no cover
            log.warning("đọc log lỗi: %s", exc)

    def _ensure_monitor(self) -> None:
        if self._monitor and self._monitor.is_alive():
            return
        self._monitor = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor.start()

    def _monitor_loop(self) -> None:
        """Giám sát: nếu bot chết bất ngờ -> tự khởi động lại với backoff."""
        while True:
            time.sleep(3)
            with self._lock:
                if self._stop_requested:
                    return
                proc = self._proc
                if proc is None:
                    return

                code = proc.poll()
                if code is None:
                    # còn sống: chạy đủ lâu thì reset backoff
                    if self.state.started_at and time.time() - self.state.started_at > HEALTHY_UPTIME:
                        self._restart_times.clear()
                    continue

                # vừa chết
                self.state.last_exit_code = code
                self.state.last_exit_at = time.time()
                self.state.status = "crashed"
                self.state.pid = None
                # QUAN TRỌNG: phải xoá _proc, nếu không điều kiện "_proc is not None"
                # bên dưới sẽ luôn đúng -> không bao giờ spawn lại (bug đã gặp).
                self._proc = None
                self.state.logs.append(f"--- exited {code} ---")
                log.warning("Bot chết, exit=%s", code)

                now = time.time()
                self._restart_times.append(now)
                recent = [t for t in self._restart_times if now - t < RESTART_WINDOW]
                if len(recent) > MAX_RESTARTS:
                    self.state.status = "crashed"
                    self.state.last_error = (
                        f"restart quá {MAX_RESTARTS} lần trong {RESTART_WINDOW}s — dừng tự động"
                    )
                    log.error(self.state.last_error)
                    return

                delay = BACKOFF[min(self.state.restarts, len(BACKOFF) - 1)]
                self.state.restarts += 1
                self.state.status = "restarting"
                log.info("Khởi động lại sau %ss (lần %s)", delay, self.state.restarts)

            # sleep ngoài lock để stop() không bị chặn
            for _ in range(int(delay * 2)):
                time.sleep(0.5)
                if self._stop_requested:
                    return
            with self._lock:
                if self._stop_requested or self._proc is not None:
                    continue
                try:
                    self._spawn()
                except Exception as exc:
                    log.error("Không spawn lại được: %s", exc)
                    self.state.last_error = str(exc)
                    return


# Singleton dùng chung cho dashboard
SUPERVISOR = BotSupervisor()


def main() -> int:
    """Chạy supervisor độc lập trong terminal (không cần dashboard)."""
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s", level=logging.INFO
    )
    sup = SUPERVISOR
    sup.start()

    def handle_sigint(signum, frame):  # noqa: ARG001
        print("\nĐang dừng...")
        sup.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_sigint)
    if os.name == "nt":
        with contextlib.suppress(AttributeError, ValueError):
            signal.signal(signal.SIGBREAK, handle_sigint)

    print("Supervisor chạy. Ctrl+C để dừng.")
    try:
        while True:
            time.sleep(5)
            st = sup.status()
            print(
                f"[{time.strftime('%H:%M:%S')}] {st['status']:10} "
                f"pid={st['pid']} uptime={st['uptime']}s restarts={st['restarts']}"
            )
    except KeyboardInterrupt:
        sup.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
