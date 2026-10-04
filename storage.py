"""SQLite lifecycle support; each capability owns its schema and database."""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from contracts import DomainError, require


@contextmanager
def connect(database: Path):
    # sqlite3's transaction context does not close its file handle.
    with closing(sqlite3.connect(database, timeout=3)) as db:
        with db:
            yield db


def initialize(database: Path, schema: str) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    with connect(database) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        require(version in (0, 1), "incompatible_storage", 503)
        if version == 0:
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            require(not tables, "unrecognized_storage", 503)
        # There is no migration in v1. Future migrations must back up before changing data.
        db.executescript(schema + "\nPRAGMA user_version=1;")

def acquire_instance_lock(data_dir: Path):
    """Same instance.lock path as the Windows Rust host's exclusive file handle."""
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = None
    try:
        lock = (data_dir / "instance.lock").open("a+b")
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if lock:
            lock.close()
        raise DomainError("instance_already_running", 409) from None
    return lock
