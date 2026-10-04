"""One run at a time (added 2026-09-25).

The 24x7 watcher ticks every 15 minutes and run_jobs.bat can be started by hand or by the daily
schedule. Two runs writing the workbook and seen_jobs.sqlite together would lose rows, so both take
an OS file lock on data/run.lock. The OS drops the lock when the process ends, even after a crash
or power loss, so a stale lock can never block future runs.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path


class RunLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.fh = None

    def acquire(self, wait_seconds: float = 0, poll: float = 5) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + wait_seconds
        while True:
            fh = open(self.path, "a+")
            try:
                if os.name == "nt":
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fh = fh
                fh.seek(0)
                fh.truncate()
                fh.write(f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}\n")
                fh.flush()
                return True
            except OSError:
                fh.close()
                if time.time() >= deadline:
                    return False
                time.sleep(poll)

    def release(self):
        if not self.fh:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self.fh.close()
        self.fh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
