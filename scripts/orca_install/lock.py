"""Cross-platform lock with conservative stale-lock handling."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import json
import os
import socket

from .errors import LockError
from .store import Store, utc_now


def _windows_pid_alive(pid: int) -> Optional[bool]:
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    error = ctypes.get_last_error()
    if error == ERROR_ACCESS_DENIED:
        # A process exists but cannot be inspected. Do not steal the lock.
        return None
    return False


def pid_is_alive(pid: int) -> Optional[bool]:
    """Return True/False/None (unknown) for a process id."""

    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    except OSError:
        return None
    return True


class InstallationLock:
    def __init__(self, store: Store, command: str):
        self.store = store
        self.command = command
        self.path = store.lock_path
        self.token = os.urandom(8).hex()
        self.acquired = False

    def _payload(self) -> bytes:
        return json.dumps(
            {
                "formatVersion": 1,
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "createdAt": utc_now(),
                "command": self.command,
                "token": self.token,
            },
            indent=2,
        ).encode("utf-8")

    def _read_lock_at(self, path: Path) -> Optional[dict]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _read_lock(self) -> Optional[dict]:
        return self._read_lock_at(self.path)

    def _owner_is_gone(self, data: Optional[dict]) -> bool:
        if not data:
            return False
        hostname = data.get("hostname")
        pid = data.get("pid")
        if (
            not isinstance(pid, int)
            or not isinstance(hostname, str)
            or hostname.casefold() != socket.gethostname().casefold()
        ):
            # Another host or malformed data: liveness cannot be verified.
            return False
        return pid_is_alive(pid) is False

    def _restore_moved_lock(self, moved: Path) -> bool:
        """Put a displaced lock back without replacing a lock created meanwhile."""

        try:
            os.link(moved, self.path)
        except FileExistsError:
            return False
        except OSError:
            # Hard links are not available everywhere; recreate the file with O_EXCL.
            try:
                raw = moved.read_bytes()
            except OSError:
                return False
            try:
                fd = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                    0o600,
                )
            except OSError:
                return False
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError:
                try:
                    self.path.unlink()
                except OSError:
                    pass
                return False
        try:
            moved.unlink()
        except OSError:
            pass
        return True

    def _reclaim_stale_lock(self, observed: dict) -> bool:
        """Move the observed stale lock aside and confirm it is still the same one.

        Checking liveness and then unlinking by path is racy: another process can
        replace the stale lock in between. Renaming the file first and comparing
        the token inside the moved file closes that window. A fresh lock that was
        moved by mistake is put back and the caller gets a LockError instead of
        both processes believing they own the lock.
        """

        token = observed.get("token")
        if not isinstance(token, str) or not token:
            # Without a token the displaced file cannot be identified safely.
            return False
        moved = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{os.urandom(6).hex()}.stale"
        )
        try:
            os.replace(self.path, moved)
        except FileNotFoundError:
            # Another process removed or replaced it first; retry with O_EXCL.
            return True
        except OSError as exc:
            raise LockError(
                f"Could not move the stale installation lock aside: {exc}"
            ) from exc

        moved_data = self._read_lock_at(moved)
        if not moved_data or moved_data.get("token") != token:
            restored = self._restore_moved_lock(moved)
            detail = (
                "the displaced lock was restored"
                if restored
                else f"the displaced lock could not be restored and remains at {moved}"
            )
            raise LockError(
                "The installation lock changed while a stale lock was being reclaimed; "
                f"another process may have acquired it ({detail}). Re-run the operation."
            )

        try:
            moved.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise LockError(
                f"The stale installation lock was moved aside but could not be removed: {exc}"
            ) from exc
        return True

    def acquire(self) -> None:
        self.store.base_dir.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                fd = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                    0o600,
                )
            except FileExistsError:
                data = self._read_lock()
                if attempt == 0 and self._owner_is_gone(data):
                    if self._reclaim_stale_lock(data):
                        continue
                owner = "unknown"
                if data:
                    owner = (
                        f"pid {data.get('pid')} on {data.get('hostname')} "
                        f"({data.get('command', 'unknown command')})"
                    )
                raise LockError(
                    f"Another installation operation is already running: {owner}. "
                    f"Lock file: {self.path}. If that process is gone, remove the lock "
                    "manually after checking it."
                ) from None
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(self._payload())
                    handle.flush()
                    os.fsync(handle.fileno())
                self.acquired = True
                return
        raise LockError(f"Could not acquire the installation lock: {self.path}")

    def release(self) -> None:
        if not self.acquired:
            return
        data = self._read_lock()
        if data and data.get("token") == self.token:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self.acquired = False

    def __enter__(self) -> "InstallationLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False


def inspect_lock(store: Store) -> Optional[str]:
    """Read-only description of an existing lock, for ``status``."""

    if not store.lock_path.exists():
        return None
    try:
        data = json.loads(store.lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return f"unreadable lock file ({store.lock_path})"
    if not isinstance(data, dict):
        return f"invalid lock file ({store.lock_path})"
    pid = data.get("pid")
    hostname = data.get("hostname")
    alive = pid_is_alive(pid) if isinstance(pid, int) else None
    state = "alive" if alive is True else ("not running" if alive is False else "unknown")
    return (
        f"pid {pid} on {hostname} ({data.get('command', 'unknown command')}), "
        f"process {state}; lock: {store.lock_path}"
    )
