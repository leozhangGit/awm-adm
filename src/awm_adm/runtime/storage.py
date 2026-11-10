"""Owned SQLite registry and per-instance stores; one process owns the directory."""

import fcntl
import hashlib
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from .protocol import RuntimeFault, dumps, loads

APPLICATION_ID = 0x41574D32
SCHEMA_VERSION = 15


def identifier(value):
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise RuntimeFault("not_found", "Unknown instance") from error
    return value


def migrate(connection, kind):
    """Only owned databases migrate; each schema change is transactional."""
    app_id = connection.execute("PRAGMA application_id").fetchone()[0]
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    if app_id != APPLICATION_ID and (app_id or version or tables):
        raise RuntimeFault("foreign_store", "Refusing a database not owned by AWM-ADM")
    if version > SCHEMA_VERSION or (version == 0 and tables):
        raise RuntimeFault("unsupported_store", "Unsupported database schema")
    connection.execute("BEGIN IMMEDIATE")
    try:
        if version < 1:
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            if kind == "registry":
                connection.execute(
                    "CREATE TABLE instances (id TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL)"
                )
            else:
                connection.execute(
                    "CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), context BLOB NOT NULL, mode TEXT NOT NULL, active TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE versions (root TEXT PRIMARY KEY, payload BLOB NOT NULL, digest TEXT NOT NULL)"
                )
        if version < 2:
            if kind == "registry":
                connection.execute(
                    "CREATE TABLE components (role TEXT PRIMARY KEY, generation TEXT NOT NULL, token TEXT NOT NULL, expires REAL NOT NULL)"
                )
            else:
                connection.execute(
                    "CREATE TABLE runs (id TEXT PRIMARY KEY, generation TEXT NOT NULL, token TEXT NOT NULL, expires REAL NOT NULL, status TEXT NOT NULL, query BLOB NOT NULL, context BLOB NOT NULL, result BLOB)"
                )
        if version < 3:
            from ..application.schema import extend

            extend(connection, kind)
        if version < 4:
            from ..learning.schema import extend as learning_extend

            learning_extend(connection, kind)
        if version < 5:
            from ..language.schema import extend as language_extend

            language_extend(connection, kind)
        if version < 6:
            from ..sources.schema import extend as source_extend

            source_extend(connection, kind)
        if version < 7:
            from ..feeds.schema import extend as feed_extend

            feed_extend(connection, kind)
        if version < 8:
            from ..application.admin_schema import extend as admin_extend

            admin_extend(connection, kind)
        if version < 9:
            from ..allowances.schema import extend as spending_extend

            spending_extend(connection, kind)
        if version < 10:
            from ..conversations.schema import extend as conversation_extend

            conversation_extend(connection, kind)
        if version < 11:
            from ..conversations.ask_schema import extend as ask_extend

            ask_extend(connection, kind)
        if version < 12:
            from ..teaching.schema import extend as teaching_extend

            teaching_extend(connection, kind)
        if version < 13:
            from ..teaching.execution_schema import extend as execution_extend

            execution_extend(connection, kind)
        if version < 14:
            from ..intake.schema import extend as intake_extend

            intake_extend(connection, kind)
        if version < 15:
            from ..lifecycle.schema import extend as lifecycle_extend

            lifecycle_extend(connection, kind)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


class Store:
    def __init__(self, root, limits):
        self.root = Path(root).absolute()
        self.limits = limits
        self.lock = RLock()
        self.generation = str(uuid4())
        self.closed = False
        self._owner = None
        try:
            if self.root.is_symlink():
                raise RuntimeFault("invalid_data_path", "Data directory must not be a symlink")
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._owner = os.open(self.root / ".owner.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeFault("already_owned", "Another app process owns this data directory") from error
            marker = self.root / ".awm-adm-v2"
            if not marker.exists():
                if set(p.name for p in self.root.iterdir()) != {".owner.lock"}:
                    raise RuntimeFault("foreign_store", "Use an empty AWM-ADM data directory")
                marker.write_text("awm-adm-store/2\n")
            if marker.is_symlink() or marker.read_text() != "awm-adm-store/2\n":
                raise RuntimeFault("foreign_store", "Invalid AWM-ADM data marker")
            if not (self.root / "registry.db").exists() and any(self.root.glob("*.db*")):
                raise RuntimeFault("corrupt_store", "Registry is missing from an existing installation")
            with self.db() as connection:
                migrate(connection, "registry")
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeFault("corrupt_store", "Registry failed integrity checks")
            self.reconcile()
            # No runtime/coordinator exists until every model has migrated and rechecked.
            with self.db() as connection, self.transaction(connection):
                connection.execute("UPDATE installation_upgrade SET status='ready' WHERE id=1")
        except BaseException:
            self.close()
            raise

    def _path(self, instance=None):
        return self.root / ("registry.db" if instance is None else f"{identifier(instance)}.db")

    @contextmanager
    def db(self, instance=None, *, create=False):
        with self.lock:
            if self.closed:
                raise RuntimeFault("stopped", "Store is closed")
            if instance:
                # Every per-model read/write shares this fence with deletion.
                with self.db() as registry:
                    state = registry.execute(
                        "SELECT status FROM instances WHERE id=?", (identifier(instance),)
                    ).fetchone()
                if state and state[0] in ("deleting", "deleted"):
                    raise RuntimeFault("gone", "Model deletion is in progress or complete")
            path = self._path(instance)
            if path.is_symlink():
                raise RuntimeFault("invalid_data_path", "Database path must not be a symlink")
            if instance and not create and not path.is_file():
                raise RuntimeFault("corrupt_store", "Registered instance store is missing")
            connection = sqlite3.connect(path, timeout=2, isolation_level=None)
            connection.row_factory = sqlite3.Row
            try:
                app_id = connection.execute("PRAGMA application_id").fetchone()[0]
                occupied = connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
                if app_id != APPLICATION_ID and (app_id or occupied):
                    raise RuntimeFault("foreign_store", "Refusing a database not owned by AWM-ADM")
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA trusted_schema=OFF")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=FULL")
                connection.execute("PRAGMA wal_autocheckpoint=32")
                maximum = (
                    self.limits.instance_storage_bytes
                    if instance
                    else min(self.limits.instance_storage_bytes, 67_108_864)
                )
                connection.execute(f"PRAGMA max_page_count={maximum // 4096}")
                yield connection
            finally:
                connection.close()

    @staticmethod
    @contextmanager
    def transaction(connection):
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def capacity(self, extra):
        size = sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())
        # Reserve room for both database and temporary journal pages.
        if size + 2 * extra + 65_536 > self.limits.installation_storage_bytes:
            raise RuntimeFault("resource_exhausted", "Installation storage allowance is exhausted")

    def reserve(self, name):
        if not isinstance(name, str) or not 1 <= len(name) <= 128 or any(ord(c) < 32 for c in name):
            raise RuntimeFault("invalid_input", "Instance name must contain 1–128 printable characters")
        with self.db() as connection, self.transaction(connection):
            if (
                connection.execute(
                    "SELECT count(*) FROM instances WHERE status NOT IN ('deleting','deleted')"
                ).fetchone()[0]
                >= self.limits.max_adms
            ):
                raise RuntimeFault("resource_exhausted", "Instance limit reached")
            self.capacity(65_536)
            key = str(uuid4())
            connection.execute("INSERT INTO instances VALUES (?,?,?)", (key, name, "creating"))
            return key

    def install(self, key, prepared, mode):
        context = dict(prepared["context"])
        context.update(instance_id=key, persistence="sqlite", background_learning=False)
        payload = dumps(prepared["snapshot"])
        if len(payload) * 2 + 65_536 > self.limits.instance_storage_bytes:
            raise RuntimeFault("resource_exhausted", "Initial model exceeds instance storage allowance")
        with self.lock:
            if self.info(key)["status"] != "creating":
                raise RuntimeFault("stale_context", "Instance initialization is no longer current")
            self.capacity(len(payload))
            with self.db(key, create=True) as connection:
                migrate(connection, "instance")
                with self.transaction(connection):
                    connection.execute(
                        "INSERT INTO versions VALUES (?,?,?)",
                        (context["theory_version"], payload, hashlib.sha256(payload).hexdigest()),
                    )
                    connection.execute(
                        "INSERT INTO state VALUES (1,?,?,?)",
                        (dumps(context), mode, context["theory_version"]),
                    )
            # Separate durable intent completion; restart reconciles a committed instance.
            with self.db() as connection:
                connection.execute(
                    "UPDATE instances SET status='ready' WHERE id=? AND status='creating'", (key,)
                )
        return self.info(key)

    def failed_creation(self, key):
        if self._path(key).exists():
            # A per-instance commit may have succeeded before registry completion
            # failed. Keep the intent for startup reconciliation, never hide it.
            return
        with self.db() as connection:
            connection.execute(
                "UPDATE instances SET status='failed' WHERE id=? AND status='creating'", (key,)
            )

    def list(self):
        with self.db() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM instances WHERE status NOT IN ('deleting','deleted') ORDER BY rowid"
                )
            ]

    def info(self, key):
        identifier(key)
        with self.db() as connection:
            row = connection.execute("SELECT * FROM instances WHERE id=?", (key,)).fetchone()
        if row is None:
            raise RuntimeFault("not_found", "Unknown instance")
        if row["status"] in ("deleting", "deleted"):
            raise RuntimeFault("gone", "Model deletion is in progress or complete")
        result = dict(row)
        if row["status"] == "ready":
            with self.db(key) as connection:
                state = connection.execute("SELECT context, mode FROM state WHERE id=1").fetchone()
                if state is None:
                    raise RuntimeFault("corrupt_store", "Instance has no active state")
                result.update(loads(state["context"]), mode=state["mode"])
        return result

    def snapshot(self, key):
        if self.info(key)["status"] != "ready":
            raise RuntimeFault("not_ready", "Instance is not ready")
        with self.db(key) as connection:
            row = connection.execute(
                "SELECT v.* FROM versions v JOIN state s ON s.active=v.root WHERE s.id=1"
            ).fetchone()
            if row is None or hashlib.sha256(row["payload"]).hexdigest() != row["digest"]:
                raise RuntimeFault("corrupt_store", "Stored model failed its content digest")
            return loads(row["payload"])

    def claim(self, key, query, context, seconds):
        with self.db(key) as connection, self.transaction(connection):
            connection.execute(
                "UPDATE runs SET status='interrupted', result=NULL WHERE status='running' AND expires<=?",
                (time.time(),),
            )
            count = connection.execute("SELECT count(*) FROM runs").fetchone()[0]
            if count >= self.limits.queue_items_per_adm:
                raise RuntimeFault("resource_exhausted", "Retained run limit reached")
            active = connection.execute("SELECT count(*) FROM runs WHERE status='running'").fetchone()[0]
            if active >= self.limits.serving_processes:
                raise RuntimeFault("busy", "Instance compute capacity is occupied")
            self.capacity(len(dumps(query)) + len(dumps(context)))
            lease = {
                "id": str(uuid4()),
                "generation": self.generation,
                "token": str(uuid4()),
                "expires": time.time() + seconds,
            }
            connection.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,NULL)",
                (*lease.values(), "running", dumps(query), dumps(context)),
            )
            return lease

    def finish(self, key, lease, result, status="completed"):
        data = dumps(result)
        with self.db(key) as connection, self.transaction(connection):
            active = connection.execute("SELECT context FROM state WHERE id=1").fetchone()
            pinned = connection.execute("SELECT context FROM runs WHERE id=?", (lease["id"],)).fetchone()
            if (
                pinned is not None
                and loads(active["context"])["policy_epoch"] != loads(pinned["context"])["policy_epoch"]
            ):
                raise RuntimeFault("stale_context", "Owner context changed during operator computation")
            self.capacity(len(data))
            changed = connection.execute(
                "UPDATE runs SET status=?, result=? WHERE id=? AND generation=? AND token=? AND status='running' AND expires>?",
                (status, data, lease["id"], self.generation, lease["token"], time.time()),
            ).rowcount
            if not changed or lease["generation"] != self.generation:
                raise RuntimeFault("stale_lease", "Run publication authority is stale")

    def abandon(self, key, lease, reason):
        with self.db(key) as connection:
            connection.execute(
                "UPDATE runs SET status=?, result=NULL WHERE id=? AND token=? AND generation=? AND status='running'",
                (reason, lease["id"], lease["token"], self.generation),
            )

    def run_info(self, key, run_id):
        self.info(key)
        with self.db(key) as connection:
            row = connection.execute(
                "SELECT id,status,context,result FROM runs WHERE id=?", (identifier(run_id),)
            ).fetchone()
        if row is None:
            raise RuntimeFault("not_found", "Unknown run")
        return {
            "id": row["id"],
            "status": row["status"],
            "context": loads(row["context"]),
            "result": loads(row["result"]) if row["result"] else None,
        }

    def component_claim(self, role):
        if role not in ("worker", "gateway"):
            raise RuntimeFault("invalid_input", "Unknown component")
        token = str(uuid4())
        with self.db() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO components VALUES (?,?,?,?)",
                (role, self.generation, token, time.time() + 15),
            )
        return {"role": role, "generation": self.generation, "token": token}

    def component_renew(self, lease):
        if lease["generation"] != self.generation:
            raise RuntimeFault("stale_lease", "Component must obtain a new lease")
        with self.db() as connection:
            now = time.time()
            changed = connection.execute(
                "UPDATE components SET expires=? WHERE role=? AND generation=? AND token=? AND expires>?",
                (now + 15, lease["role"], self.generation, lease["token"], now),
            ).rowcount
            if not changed or lease["generation"] != self.generation:
                raise RuntimeFault("stale_lease", "Component must obtain a new lease")
        return {"status": "idle", "jobs_available": False, "learning_implemented": False}

    def components(self):
        with self.db() as connection:
            rows = {row["role"]: row for row in connection.execute("SELECT * FROM components")}
        return {
            role: bool(
                role in rows
                and rows[role]["generation"] == self.generation
                and rows[role]["expires"] > time.time()
            )
            for role in ("worker", "gateway")
        }

    def reconcile(self):
        with self.db() as connection:
            connection.execute("DELETE FROM components")
        for row in self.list():
            if row["status"] not in ("creating", "ready"):
                if self._path(row["id"]).is_file():
                    with self.db(row["id"]) as connection:
                        migrate(connection, "instance")
                continue
            key = row["id"]
            if not self._path(key).is_file():
                if row["status"] == "creating":
                    self.failed_creation(key)
                    continue
                raise RuntimeFault("corrupt_store", "Registered instance store is missing")
            with self.db(key) as connection:
                migrate(connection, "instance")
                if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise RuntimeFault("corrupt_store", "Instance failed integrity checks")
                state = connection.execute("SELECT context FROM state WHERE id=1").fetchone()
                if state is not None and loads(state["context"])["instance_id"] != key:
                    raise RuntimeFault("corrupt_store", "Instance identity differs from registry")
                connection.execute("UPDATE runs SET status='interrupted', result=NULL WHERE status='running'")
            if row["status"] == "creating":
                with self.db() as connection:
                    connection.execute(
                        "UPDATE instances SET status=? WHERE id=?", ("ready" if state else "failed", key)
                    )
            if state:
                self.snapshot(key)
            elif row["status"] == "ready":
                raise RuntimeFault("corrupt_store", "Instance state is missing")

    def close(self):
        with self.lock:
            self.closed = True
            if self._owner is not None:
                os.close(self._owner)
                self._owner = None
