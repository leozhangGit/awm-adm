"""Exclusive gateway store: authenticated ciphertext and an at-most-once dispatch fence."""

import base64
import fcntl
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ..runtime.protocol import RuntimeFault, dumps, loads

LABEL = b"awm-adm-provider-credential/1"


class GatewayStore:
    def __init__(self, root, master_key, *, static_dir=None):
        self.root = Path(root)
        self.lock = RLock()
        self._owner = None
        self.static_dir = Path(static_dir) if static_dir else None
        if self.root.is_symlink():
            raise ValueError("Gateway directory cannot be a symlink")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.cipher = Fernet(master_key)
        try:
            self._owner = os.open(self.root / ".gateway-owner", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            marker = self.root / ".awm-gateway-v1"
            if marker.is_symlink():
                raise ValueError("Invalid gateway marker")
            if marker.exists():
                if marker.read_text() != "awm-gateway/1\n" or not (self.root / "gateway.db").is_file():
                    raise ValueError("Established gateway store is missing or invalid")
            elif set(p.name for p in self.root.iterdir()) - {
                ".gateway-owner",
                "bootstrap.db",
                "bootstrap.db-wal",
                "bootstrap.db-shm",
            }:
                raise ValueError("Foreign gateway directory")
            with self.db() as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                appid = db.execute("PRAGMA application_id").fetchone()[0]
                if tables and appid != 0x41574735:
                    raise ValueError("Foreign gateway database")
                db.execute(f"PRAGMA application_id={0x41574735}")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS keys (id INTEGER PRIMARY KEY CHECK(id=1), ciphertext BLOB NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS connections (id TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL, config BLOB NOT NULL, credential BLOB, PRIMARY KEY(id,version))"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS dispatches (id TEXT PRIMARY KEY, digest TEXT NOT NULL, status TEXT NOT NULL, result BLOB, created REAL NOT NULL, request BLOB, acknowledged INTEGER NOT NULL DEFAULT 0)"
                )
                db.execute("CREATE TABLE IF NOT EXISTS redactions (id TEXT PRIMARY KEY)")
                row = db.execute("SELECT ciphertext FROM keys WHERE id=1").fetchone()
                if row:
                    self.private = serialization.load_pem_private_key(
                        self.cipher.decrypt(row[0]), password=None
                    )
                else:
                    self.private = rsa.generate_private_key(public_exponent=65537, key_size=4096)
                    pem = self.private.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                    db.execute("INSERT INTO keys VALUES(1,?)", (self.cipher.encrypt(pem),))
                unknown = dumps(
                    {"status": "outcome_unknown", "error": "gateway_restarted", "usage": None, "text": None}
                )
                db.execute(
                    "UPDATE dispatches SET status='outcome_unknown',result=? WHERE status='dispatched'",
                    (unknown,),
                )
            marker.write_text("awm-gateway/1\n")
            raw = self.private.public_key().public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            self.public = {
                "key_id": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "algorithm": "RSA-OAEP-256",
                "spki": base64.b64encode(raw).decode(),
            }
        except BaseException:
            self.close()
            raise

    @contextmanager
    def db(self):
        with self.lock:
            path = self.root / "gateway.db"
            if path.is_symlink():
                raise ValueError("Gateway database cannot be a symlink")
            db = sqlite3.connect(path, timeout=2, isolation_level=None)
            db.row_factory = sqlite3.Row
            try:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=FULL")
                db.execute("PRAGMA max_page_count=16384")
                db.execute("PRAGMA trusted_schema=OFF")
                yield db
            finally:
                db.close()

    @staticmethod
    def _credential(value):
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 256
            or any(not 33 <= ord(c) <= 126 for c in value)
        ):
            raise ValueError("Invalid provider credential")
        return value

    def install(self, config):
        uid, version = config["id"], config["version"]
        with self.db() as db:
            old = db.execute(
                "SELECT digest FROM connections WHERE id=? AND version=?", (uid, version)
            ).fetchone()
            if old:
                if old[0] != config["configuration_digest"]:
                    raise ValueError("Gateway configuration identity conflict")
                return
            if db.execute("SELECT count(*) FROM connections").fetchone()[0] >= 1000:
                raise RuntimeFault("quota_exceeded", "Retained gateway connection allowance exhausted")
            value = None
            if config["credential_mode"] == "managed":
                if config.get("sealed_credential"):
                    if config.get("sealing_key_id") != self.public["key_id"]:
                        raise ValueError("Gateway sealing identity changed")
                    decrypted = self.private.decrypt(
                        base64.b64decode(config["sealed_credential"], validate=True),
                        padding.OAEP(
                            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=LABEL
                        ),
                    )
                    envelope = json.loads(decrypted)
                    if (
                        set(envelope) != {"credential", "provider", "idempotency_key"}
                        or envelope["provider"] != config["provider"]
                        or envelope["idempotency_key"] != config["idempotency_key"]
                    ):
                        raise ValueError("Sealed credential belongs to different configuration")
                    value = self._credential(envelope["credential"])
                else:
                    row = db.execute(
                        "SELECT * FROM connections WHERE id=? AND version=?", (uid, version - 1)
                    ).fetchone()
                    if (
                        row is None
                        or loads(row["config"])["provider"] != config["provider"]
                        or row["credential"] is None
                    ):
                        raise ValueError("Supply a new sealed credential")
                    value = self._decrypt(row)
            elif config["credential_mode"] == "static":
                self._static(config["provider"])
            safe = {k: v for k, v in config.items() if k not in ("sealed_credential", "sealing_key_id")}
            encrypted = (
                self.cipher.encrypt(dumps({"id": uid, "version": version, "credential": value}))
                if value
                else None
            )
            db.execute(
                "INSERT INTO connections VALUES(?,?,?,?,?)",
                (uid, version, config["configuration_digest"], dumps(safe), encrypted),
            )

    def _static(self, provider):
        if provider not in ("openai", "anthropic") or self.static_dir is None:
            raise ValueError("Static credential unavailable")
        path = self.static_dir / (provider + "-key")
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 512:
            raise ValueError("Static credential unavailable")
        return self._credential(path.read_text().strip())

    def _decrypt(self, row):
        value = loads(self.cipher.decrypt(row["credential"]))
        if value["id"] != row["id"] or value["version"] != row["version"]:
            raise ValueError("Credential binding mismatch")
        return self._credential(value["credential"])

    def connection(self, uid, version, digest):
        with self.db() as db:
            row = db.execute("SELECT * FROM connections WHERE id=? AND version=?", (uid, version)).fetchone()
            if row is None or row["digest"] != digest:
                raise ValueError("Gateway connection is not synchronized")
            config = loads(row["config"])
            key = (
                self._decrypt(row)
                if row["credential"]
                else self._static(config["provider"])
                if config["credential_mode"] == "static"
                else ""
            )
            return config, key

    def lookup(self, uid):
        with self.db() as db:
            row = db.execute("SELECT * FROM dispatches WHERE id=?", (uid,)).fetchone()
            return dict(row) if row else None

    def begin(self, uid, fingerprint, request=None):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT * FROM dispatches WHERE id=?", (uid,)).fetchone()
                if row:
                    if row["digest"] != fingerprint:
                        raise ValueError("Dispatch identity conflict")
                    db.commit()
                    return False
                if db.execute("SELECT count(*) FROM dispatches").fetchone()[0] >= 10000:
                    raise RuntimeFault("quota_exceeded", "Gateway dispatch allowance exhausted")
                db.execute(
                    "INSERT INTO dispatches(id,digest,status,result,created,request) VALUES(?,?,'dispatched',NULL,?,?)",
                    (uid, fingerprint, time.time(), dumps(request) if request else None),
                )
                db.commit()
                return True
            except BaseException:
                db.rollback()
                raise

    def finish(self, uid, outcome):
        with self.db() as db:
            if db.execute("SELECT 1 FROM redactions WHERE id=?", (uid,)).fetchone():
                from ..lifecycle.service import accounting_outcome

                outcome = accounting_outcome(outcome)
            db.execute(
                "UPDATE dispatches SET status=?,result=? WHERE id=? AND status='dispatched'",
                (outcome["status"], dumps(outcome), uid),
            )

    def forget(self, uid):
        """Durably remove model payloads; late responses retain only accounting."""
        from ..lifecycle.service import accounting_outcome

        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("INSERT OR IGNORE INTO redactions VALUES(?)", (uid,))
                row = db.execute("SELECT * FROM dispatches WHERE id=?", (uid,)).fetchone()
                if row:
                    original = loads(row["request"]) if row["request"] else {}
                    request = {"lease": original["lease"]} if original.get("lease") else None
                    outcome = accounting_outcome(loads(row["result"])) if row["result"] else None
                    db.execute(
                        "UPDATE dispatches SET request=?,result=? WHERE id=?",
                        (dumps(request) if request else None, dumps(outcome) if outcome else None, uid),
                    )
                else:
                    db.execute(
                        "INSERT INTO dispatches(id,digest,status,created,acknowledged) VALUES(?,'','not_dispatched',?,1)",
                        (uid, time.time()),
                    )
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def close(self):
        if self._owner is not None:
            os.close(self._owner)
            self._owner = None
