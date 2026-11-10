"""Paired offline recovery bundles. Never open a runtime or decrypt a secret here."""

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from uuid import UUID

from .. import __version__
from ..runtime.protocol import dumps, loads
from ..runtime.storage import APPLICATION_ID, SCHEMA_VERSION

PROFILE = "awm-adm-service-backup/1"
MARKERS = {
    "app": (".awm-adm-v2", "awm-adm-store/2\n", ".owner.lock"),
    "gateway": (".awm-gateway-v1", "awm-gateway/1\n", ".gateway-owner"),
}
MAX_FILES = 1003
MAX_BYTES = 6 * 1024**3


def safe_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Symlink paths are unsupported")
    return path


@contextmanager
def owned(root, kind):
    root = safe_path(root)
    marker, content, lock = MARKERS[kind]
    if not root.is_dir() or (root / marker).is_symlink() or (root / marker).read_text() != content:
        raise ValueError("Not an established service store")
    fd = os.open(root / lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield root
    finally:
        os.close(fd)


@contextmanager
def read_db(path):
    path = safe_path(path)
    if not path.is_file():
        raise ValueError("Required database missing")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def check_db(db, kind, schema=SCHEMA_VERSION):
    expected = APPLICATION_ID if kind == "app" else 0x41574735
    if db.execute("PRAGMA application_id").fetchone()[0] != expected:
        raise ValueError("Foreign database")
    if kind == "app" and db.execute("PRAGMA user_version").fetchone()[0] != schema:
        raise ValueError("Backup requires current service schema")
    if db.execute("PRAGMA integrity_check").fetchall()[0][0] != "ok":
        raise ValueError("Database failed integrity check")


def database_names(app, schema=SCHEMA_VERSION):
    with read_db(app / "registry.db") as db:
        check_db(db, "app", schema)
        rows = db.execute("SELECT id,status FROM instances").fetchall()
    names = {"registry.db"}
    for row in rows:
        if str(UUID(row["id"])) != row["id"]:
            raise ValueError("Invalid registered identity")
        name = row["id"] + ".db"
        if (app / name).exists():
            names.add(name)
        elif row["status"] == "ready":
            raise ValueError("Established instance database is missing")
    if {p.name for p in app.glob("*.db")} != names:
        raise ValueError("Unregistered database in service directory")
    return sorted(names)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sync_tree(root):
    for path in root.rglob("*"):
        if path.is_file():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
    for path in [*sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True), root]:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextmanager
def staging(destination):
    destination = safe_path(destination)
    if destination.exists():
        raise ValueError("Destination must not exist; never overwrite a recovery artifact")
    parent = destination.parent
    if not parent.is_dir():
        raise ValueError("Destination parent must exist")
    temporary = Path(tempfile.mkdtemp(prefix=".awm-recovery-", dir=parent))
    try:
        yield temporary
        sync_tree(temporary)
        # Destination is operator-owned; a competing local administrator is outside
        # the trust boundary. Recheck to avoid ordinary accidental replacement.
        if destination.exists():
            raise ValueError("Destination appeared during operation")
        temporary.rename(destination)
        fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def backup(app, gateway, destination):
    destination = safe_path(destination)
    with ExitStack() as locks:
        roots = {k: locks.enter_context(owned(p, k)) for k, p in (("app", app), ("gateway", gateway))}
        if roots["app"] == roots["gateway"] or any(destination.is_relative_to(r) for r in roots.values()):
            raise ValueError("Recovery destination must be outside both stores")
        names = {"app": database_names(roots["app"]), "gateway": ["gateway.db"]}
        total = 0
        for kind, entries in names.items():
            for name in entries:
                with read_db(roots[kind] / name) as db:
                    check_db(db, kind)
                    total += (
                        db.execute("PRAGMA page_count").fetchone()[0]
                        * db.execute("PRAGMA page_size").fetchone()[0]
                    )
        # Logical pages include committed WAL growth; the main file alone can be
        # much smaller than the database we are about to copy.
        if total > MAX_BYTES or sum(map(len, names.values())) + 2 > MAX_FILES:
            raise ValueError("Backup exceeds supported envelope")
        with staging(destination) as out:
            files = {}
            for kind, root in roots.items():
                target = out / kind
                target.mkdir(mode=0o700)
                marker, content, _ = MARKERS[kind]
                (target / marker).write_text(content)
                for name in names[kind]:
                    with read_db(root / name) as source, closing(sqlite3.connect(target / name)) as copied:
                        check_db(source, kind)
                        source.backup(copied)
                        copied.execute("PRAGMA journal_mode=DELETE")
                        check_db(copied, kind)
                    os.chmod(target / name, 0o600)
                for path in target.iterdir():
                    files[f"{kind}/{path.name}"] = {"bytes": path.stat().st_size, "sha256": sha(path)}
            manifest = {
                "profile": PROFILE,
                "version": __version__,
                "schema": SCHEMA_VERSION,
                "created_at_ms": int(time.time() * 1000),
                "files": files,
                "secrets_included": False,
                "gateway_ciphertext_included": True,
                "capture": "paired_exclusive_locks_sqlite_backup",
            }
            (out / "manifest.json").write_bytes(dumps(manifest))
    return {
        "profile": PROFILE,
        "status": "captured",
        "files": len(files),
        "bytes": sum(f["bytes"] for f in files.values()),
    }


def verify(bundle):
    root = safe_path(bundle)
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink() or manifest_path.stat().st_size > 512_000:
        raise ValueError("Invalid backup manifest")
    manifest = loads(manifest_path.read_bytes())
    if manifest.get("profile") != PROFILE or manifest.get("schema") not in (
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        SCHEMA_VERSION,
    ):
        raise ValueError("Unsupported recovery bundle")
    files = manifest.get("files", {})
    if not 4 <= len(files) <= MAX_FILES or sum(f["bytes"] for f in files.values()) > MAX_BYTES:
        raise ValueError("Invalid backup size")
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("Unsupported backup entry")
        if path.is_file():
            actual.add(str(path.relative_to(root)))
    if actual != {"manifest.json", *files}:
        raise ValueError("Backup inventory mismatch")
    for name, record in files.items():
        parts = Path(name).parts
        if len(parts) != 2 or parts[0] not in MARKERS or parts[1] in (".", ".."):
            raise ValueError("Unsafe backup entry")
        path = root / name
        if path.stat().st_size != record["bytes"] or sha(path) != record["sha256"]:
            raise ValueError("Backup content digest mismatch")
    for kind, (marker, content, _) in MARKERS.items():
        if (root / kind / marker).read_text() != content:
            raise ValueError("Backup marker mismatch")
    expected = {"app/" + n for n in database_names(root / "app", manifest["schema"])}
    expected |= {"app/.awm-adm-v2", "gateway/.awm-gateway-v1", "gateway/gateway.db"}
    if set(files) != expected:
        raise ValueError("Unexpected backup file")
    for name in files:
        if name.endswith(".db"):
            with read_db(root / name) as db:
                check_db(db, name.split("/")[0], manifest["schema"])
    return manifest


def restore(bundle, destination):
    manifest = verify(bundle)
    root = safe_path(bundle)
    destination = safe_path(destination)
    if destination.is_relative_to(root):
        raise ValueError("Restore destination must be outside the backup")
    with staging(destination) as out:
        for kind in MARKERS:
            (out / kind).mkdir(mode=0o700)
        for name in manifest["files"]:
            shutil.copyfile(root / name, out / name)
            os.chmod(out / name, 0o600)
        with closing(sqlite3.connect(out / "app/registry.db")) as db, db:
            db.execute("UPDATE credentials SET revoked=1")
            if manifest["schema"] >= 9:
                row = db.execute("SELECT body FROM spending_control WHERE id=1").fetchone()
                spending = json.loads(row[0])
                spending["enabled"] = False
                db.execute(
                    "UPDATE spending_control SET generation=generation+1,body=? WHERE id=1",
                    (json.dumps(spending),),
                )
            if manifest["schema"] >= 8:
                db.execute("DELETE FROM auth_tickets")
                db.execute("UPDATE auth_control SET legacy_until=0")
                db.execute("UPDATE administrator SET generation=generation+1")
            db.execute("DELETE FROM components")
            db.execute("UPDATE learning_control SET enabled=0,generation=generation+1")
            # A rollback cannot prove a formerly ready grant was never dispatched
            # after capture. Retain its full reservation rather than refunding it.
            unknown = dumps(
                {"status": "outcome_unknown", "error": "service_restored", "usage": None, "text": None}
            )
            db.execute(
                "UPDATE grants SET status='outcome_unknown',outcome=?,unresolved=1 WHERE status IN ('ready','leased','dispatched')",
                (unknown,),
            )
        paused = 0
        for name in database_names(out / "app", manifest["schema"]):
            if name == "registry.db":
                continue
            with closing(sqlite3.connect(out / "app" / name)) as db, db:
                for uid, data in db.execute("SELECT id,data FROM feeds").fetchall():
                    value = loads(data)
                    value["enabled"] = False
                    value["generation"] += 1
                    db.execute("UPDATE feeds SET data=? WHERE id=?", (dumps(value), uid))
                    paused += 1
        with closing(sqlite3.connect(out / "gateway/gateway.db")) as db, db:
            db.execute(
                "UPDATE dispatches SET status='outcome_unknown',result=? WHERE status='dispatched'",
                (unknown,),
            )
        report = {
            "profile": "awm-adm-service-restore/1",
            "status": "restored_offline",
            "backup_manifest_sha256": sha(root / "manifest.json"),
            "remote_calls_enabled": False,
            "feeds_paused": paused,
            "sessions_and_scoped_tokens_revoked": True,
            "external_usage_after_backup": "unknown_requires_owner_reconciliation",
            "startup_reconciliation_required": True,
        }
        (out / "restore.json").write_bytes(dumps(report))
    return report


def main(arguments):
    import argparse

    parser = argparse.ArgumentParser(prog="awm-adm operations")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("backup")
    capture.add_argument("--app-data", type=Path, required=True)
    capture.add_argument("--gateway-data", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify-backup")
    check.add_argument("bundle", type=Path)
    recover = commands.add_parser("restore")
    recover.add_argument("bundle", type=Path)
    recover.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(arguments)
    try:
        if args.command == "backup":
            result = backup(args.app_data, args.gateway_data, args.output)
        elif args.command == "restore":
            result = restore(args.bundle, args.output)
        else:
            value = verify(args.bundle)
            result = {"status": "verified", "files": len(value["files"]), "schema": value["schema"]}
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        # Paths, source content and database/credential values never enter CLI output.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "recovery_check_failed",
                    "action": "Check stopped owners, paths, schema, integrity and free space",
                }
            )
        )
        return 2
