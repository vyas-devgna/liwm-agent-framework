"""Durable JSON I/O: atomic writes, advisory locking, backups, recovery.

Several agents may run against the same profile at the same time (two Claude
Code sessions, a Codex session, a cron retrospective).  Everything in this
module exists so that concurrency and crashes degrade into "retry" rather than
"corrupted profile".

Guarantees provided here:

* **Atomic replace** - readers never observe a half-written file.
* **Advisory locking** - a cross-platform ``O_CREAT|O_EXCL`` lock with stale
  detection, so no ``fcntl``/``msvcrt`` divergence.
* **Backups** - a timestamped copy is taken before a destructive rewrite.
* **Recovery** - a corrupt file is quarantined (never silently deleted) and the
  caller is told, so it can rebuild from the event log.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "utc_now",
    "canonical_json",
    "sha256_of",
    "read_json",
    "write_json_atomic",
    "FileLock",
    "LockTimeout",
    "CorruptFile",
    "backup_file",
    "prune_backups",
    "quarantine_corrupt",
    "read_json_resilient",
]


class LockTimeout(RuntimeError):
    """Raised when an advisory lock could not be acquired in time."""


class CorruptFile(ValueError):
    """Raised when a JSON file exists but cannot be parsed."""


def utc_now() -> str:
    """ISO-8601 UTC timestamp with second precision and a trailing ``Z``."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_ms() -> str:
    """ISO-8601 UTC timestamp with microsecond precision.

    Microseconds, not milliseconds: event ordering is load-bearing (a rejection
    must reliably precede the observation that follows it), and a millisecond is
    long enough for several events on a fast machine.
    """
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json(obj) -> str:
    """Stable serialisation used for hashing and for on-disk determinism."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(obj) -> str:
    """SHA-256 of the canonical JSON form of *obj*."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def read_json(path, default=None):
    """Read JSON, returning *default* when missing.

    Raises :class:`CorruptFile` when the file exists but does not parse.
    """
    p = Path(path)
    if not p.exists():
        return default
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - platform dependent
        raise CorruptFile("cannot read %s: %s" % (p, exc)) from exc
    if not text.strip():
        raise CorruptFile("empty file: %s" % p)
    try:
        return json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise CorruptFile("invalid JSON in %s: %s" % (p, exc)) from exc


def write_json_atomic(path, data, indent=2, fsync=True) -> Path:
    """Write *data* to *path* atomically.

    The temp file is created in the destination directory so ``os.replace``
    stays within one filesystem and is therefore atomic.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("%s.%d.%s.tmp" % (p.name, os.getpid(), os.urandom(4).hex()))
    payload = json.dumps(data, indent=indent, sort_keys=False, ensure_ascii=False)
    if not payload.endswith("\n"):
        payload += "\n"
    try:
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            if fsync:
                os.fsync(fh.fileno())
        os.replace(tmp, p)
        try:
            os.chmod(p, 0o600)
        except OSError:  # pragma: no cover - ACL semantics vary on Windows
            pass
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:  # pragma: no cover
                pass
    if fsync:
        # Durably record the directory entry too, where the platform allows it.
        try:  # pragma: no cover - not supported on Windows
            dir_fd = os.open(str(p.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            pass
    return p


class FileLock:
    """Cross-platform advisory lock based on exclusive file creation.

    ``os.open(..., O_CREAT | O_EXCL)`` is atomic on POSIX and Windows alike, so
    this needs no platform-specific locking API.  Locks carry owner metadata and
    are broken when older than *stale_after* seconds, which prevents a crashed
    agent from wedging the profile forever.
    """

    def __init__(self, path, timeout=10.0, poll=0.05, stale_after=120.0):
        self.path = Path(path)
        self.timeout = float(timeout)
        self.poll = float(poll)
        self.stale_after = float(stale_after)
        self._fd = None
        self._token = os.urandom(16).hex()
        self.broke_stale_lock = False

    # -- internals ---------------------------------------------------------
    def _payload(self):
        return {
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "acquired_at": utc_now_ms(),
            "monotonic": time.time(),
            "token": self._token,
        }

    def _owner_is_alive(self, pid):
        """Is *pid* still running?  ``None`` when the platform cannot say.

        Liveness is what separates "the owner crashed, take the lock" from
        "the owner is mid-write, wait", so getting it wrong either wedges the
        profile or corrupts it.

        The POSIX idiom ``os.kill(pid, 0)`` must never run on Windows.  There,
        ``os.kill`` maps every signal other than ``CTRL_C_EVENT`` and
        ``CTRL_BREAK_EVENT`` onto ``TerminateProcess`` -- so "probing" a pid
        kills it, and since a lock records the pid of whoever took it, a second
        thread in the same process would terminate its own agent.  Windows
        therefore gets a real, non-destructive probe via ``OpenProcess`` plus
        ``GetExitCodeProcess``; the exit-code check matters because a handle can
        outlive the process it refers to.
        """
        if os.name == "posix":
            try:
                os.kill(pid, 0)
                return True
            except ProcessLookupError:
                return False
            except (OSError, PermissionError):
                # A live process owned by another user: not ours to reclaim.
                return True
        if os.name == "nt":
            return self._windows_owner_is_alive(pid)
        return None

    @staticmethod
    def _windows_owner_is_alive(pid):  # pragma: no cover - exercised on Windows CI
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError:
            return None

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_ACCESS_DENIED = 5
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        # Declaring the signatures is not optional on 64-bit Windows: ctypes
        # defaults restype to c_int, which truncates a 64-bit HANDLE.  Closing
        # a truncated handle closes whatever else happens to live at that value
        # in this process, which is a memorable way to corrupt an unrelated
        # file handle rather than merely to get a wrong answer.
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                                ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # Access denied means the process exists but belongs to someone
            # else, which is emphatically not a lock we may break.
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    def _is_stale(self) -> bool:
        try:
            raw = self.path.read_text(encoding="utf-8")
            info = json.loads(raw)
            age = time.time() - float(info.get("monotonic", 0.0))
            if info.get("host") == socket.gethostname():
                pid = int(info.get("pid", -1))
                if pid > 0:
                    alive = self._owner_is_alive(pid)
                    if alive is not None:
                        return not alive
        except (OSError, ValueError, TypeError):
            # Unreadable lock file: fall back to mtime, then treat as stale.
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                return True
        return age > self.stale_after

    def _owns_current_file(self):
        try:
            info = json.loads(self.path.read_text(encoding="utf-8"))
            return info.get("token") == self._token
        except (OSError, ValueError, TypeError):
            return False

    # -- public API --------------------------------------------------------
    def acquire(self) -> "FileLock":
        """Take the lock, or raise :class:`LockTimeout`.  Never spin forever.

        The deadline is checked on *every* path out of a failed attempt,
        including the one where a stale lock was reclaimed.  An earlier version
        retried the stale branch without checking, which was unreachable on
        POSIX and an unbounded busy loop on Windows: Windows refuses to delete
        a file another handle still has open, so ``unlink`` failed, the failure
        was swallowed, and the loop restarted immediately with no sleep and no
        deadline.  A lock LIWM cannot delete must degrade into a timeout the
        caller can report, not a pegged CPU core.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, canonical_json(self._payload()).encode("utf-8"))
                self._fd = fd
                return self
            except OSError as exc:
                if exc.errno not in (errno.EEXIST,):  # pragma: no cover
                    raise

            reclaimed = False
            if self._is_stale():
                try:
                    self.path.unlink()
                    self.broke_stale_lock = True
                    reclaimed = True
                except OSError:
                    # Lost the race, or the platform will not delete a file
                    # that is still open.  Either way, fall through and wait.
                    pass

            if time.time() >= deadline:
                raise LockTimeout(
                    "could not acquire lock %s within %.1fs" % (self.path, self.timeout))
            if not reclaimed:
                time.sleep(self.poll)

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:  # pragma: no cover
                pass
            self._fd = None
        if self._owns_current_file():
            try:
                self.path.unlink()
            except OSError:  # pragma: no cover - already gone
                pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def backup_file(path, backups_dir, tag="auto"):
    """Copy *path* into *backups_dir* under a timestamped name.

    Returns the backup path, or ``None`` when the source does not exist.
    """
    src = Path(path)
    if not src.exists():
        return None
    dest_dir = Path(backups_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = dest_dir / ("%s.%s.%s.bak" % (src.name, stamp, tag))
    shutil.copy2(src, dest)
    return dest


def prune_backups(backups_dir, keep=40, prefix=None) -> int:
    """Keep only the *keep* newest backups; return how many were removed."""
    d = Path(backups_dir)
    if not d.is_dir():
        return 0
    files = [f for f in d.iterdir() if f.is_file() and f.name.endswith(".bak")]
    if prefix:
        files = [f for f in files if f.name.startswith(prefix)]
    files.sort(key=lambda f: f.name, reverse=True)
    removed = 0
    for f in files[keep:]:
        try:
            f.unlink()
            removed += 1
        except OSError:  # pragma: no cover
            pass
    return removed


def quarantine_corrupt(path, logs_dir):
    """Move a corrupt file aside so it is never silently lost."""
    src = Path(path)
    if not src.exists():
        return None
    dest_dir = Path(logs_dir) / "corrupt"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = dest_dir / ("%s.%s.corrupt" % (src.name, stamp))
    shutil.move(str(src), str(dest))
    return dest


def read_json_resilient(path, backups_dir=None, logs_dir=None, default=None):
    """Read JSON, recovering from corruption via the newest usable backup.

    Returns ``(data, recovery_note)`` where *recovery_note* is ``None`` on the
    happy path and otherwise a short human-readable description of what
    happened.  Callers decide whether to rebuild from the event log instead.
    """
    p = Path(path)
    try:
        data = read_json(p, default=None)
        if data is not None:
            return data, None
        return default, None
    except CorruptFile as exc:
        note = str(exc)

    if logs_dir is not None:
        moved = quarantine_corrupt(p, logs_dir)
        note += " | quarantined to %s" % moved

    if backups_dir is not None:
        d = Path(backups_dir)
        if d.is_dir():
            candidates = sorted(
                (f for f in d.iterdir() if f.is_file() and f.name.startswith(p.name)),
                key=lambda f: f.name,
                reverse=True,
            )
            for cand in candidates:
                try:
                    data = read_json(cand)
                except CorruptFile:
                    continue
                if data is not None:
                    write_json_atomic(p, data)
                    return data, note + " | restored from backup %s" % cand.name
    return default, note + " | no usable backup"
