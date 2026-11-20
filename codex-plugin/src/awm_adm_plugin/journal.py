"""Private per-project state, atomic replacement and cross-process serialization."""

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .client import Problem


class Journal:
    def __init__(self, root):
        self.root = Path(root)

    @contextmanager
    def project(self, project):
        path = Path(project).resolve(strict=True)
        stat = path.stat()
        identity = [str(path), stat.st_dev, stat.st_ino, getattr(stat, "st_birthtime", None)]
        key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink():
            raise Problem("unsafe_state", "Plugin state must be in a private directory, not a symbolic link.")
        self.root.chmod(0o700)
        fd = os.open(self.root / (key + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            target = self.root / (key + ".json")
            if target.is_symlink():
                raise Problem("unsafe_state", "Refusing a linked binding file.")
            if target.exists():
                if target.stat().st_size > 8_388_608:
                    raise Problem(
                        "state_full", "The private project journal needs archiving before more work."
                    )
                state = json.loads(target.read_text())
                if (
                    not isinstance(state, dict)
                    or state.get("profile") != "awm-adm-project/1"
                    or state.get("identity") != identity
                    or not isinstance(state.get("work"), dict)
                    or not {"binding", "creation"}.issubset(state)
                ):
                    raise Problem("invalid_state", "The saved project binding does not match this project.")
            else:
                state = {
                    "profile": "awm-adm-project/1",
                    "identity": identity,
                    "binding": None,
                    "creation": None,
                    "work": {},
                }

            def save():
                raw = json.dumps(state, ensure_ascii=False, allow_nan=False).encode()
                if len(raw) > 8_388_608:
                    raise Problem(
                        "state_full", "The private project journal needs archiving before more work."
                    )
                temp = self.root / ("." + str(uuid4()))
                out = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                try:
                    with os.fdopen(out, "wb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp, target)
                    directory = os.open(self.root, os.O_RDONLY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                finally:
                    temp.unlink(missing_ok=True)

            yield state, save
        except (json.JSONDecodeError, UnicodeError):
            raise Problem(
                "invalid_state", "The project journal is unreadable; preserve it before recovery."
            ) from None
        finally:
            os.close(fd)
