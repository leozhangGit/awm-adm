"""Local single-administrator authentication. No provider or model dependency."""

import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from contextlib import contextmanager
from threading import BoundedSemaphore
from uuid import uuid4

from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from ..runtime.protocol import RuntimeFault
from .auth import fingerprint

SESSION_SECONDS = 28_800
COOKIE = "awm_admin_session"
# Bound password work across public and private Authority instances in this process.
PASSWORD_WORK = BoundedSemaphore(1)


def email_identifier(value):
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(
        r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value
    ):
        raise RuntimeFault("invalid_input", "Use a valid ASCII email identifier")
    return value


def password_bytes(value, *, new=False):
    value = unicodedata.normalize("NFC", value)
    if not (15 if new else 1) <= len(value) <= 1024:
        raise RuntimeFault("invalid_input", "Password must have 15–1024 characters")
    return value.encode("utf-8")


def hash_password(value):
    return Argon2id(
        salt=secrets.token_bytes(16), length=32, iterations=2, lanes=1, memory_cost=19_456
    ).derive_phc_encoded(value)


def verify_password(value, encoded):
    try:
        Argon2id.verify_phc_encoded(value, encoded)
        return True
    except (InvalidKey, ValueError):
        return False


def csrf_for(token):
    return hmac.new(token.encode(), b"awm-adm-admin-csrf/1", hashlib.sha256).hexdigest()


class Administrator:
    def __init__(self, authority):
        self.auth = authority
        self.store = authority.store

    def metadata(self):
        with self.store.db() as db:
            row = db.execute("SELECT uid,email,generation FROM administrator WHERE id=1").fetchone()
        return (
            None
            if row is None
            else {
                "profile": "awm-adm-v3-adminmetadata/0.1",
                "id": row["uid"],
                "email": row["email"],
                "session_generation": row["generation"],
                "setup_complete": True,
            }
        )

    def ticket(self, kind):
        """Private operator only; replace older ticket, never return an account password."""
        if kind not in ("bootstrap", "recovery"):
            raise RuntimeFault("invalid_input", "Unknown credential purpose")
        ttl = 900 if kind == "bootstrap" else 600
        token = secrets.token_urlsafe(48)
        with self.store.db() as db, self.store.transaction(db):
            exists = db.execute("SELECT 1 FROM administrator").fetchone() is not None
            if exists != (kind == "recovery"):
                raise RuntimeFault("conflict", "Credential purpose does not match setup state")
            db.execute(
                "INSERT OR REPLACE INTO auth_tickets VALUES(?,?,?)",
                (kind, fingerprint(token), time.time() + ttl),
            )
            # A freshly issued bootstrap replaces the initial legacy setup window.
            if kind == "bootstrap":
                db.execute("UPDATE auth_control SET legacy_until=0")
            db.execute("DELETE FROM auth_attempts WHERE key LIKE ?", (kind + ":%",))
        return {"token": token, "expires_in": ttl, "purpose": kind}

    def _reserve(self, operation, source, email=""):
        # Real peer address, never client-controlled X-Forwarded-For. Hash identifiers.
        keys = [operation + ":source:" + fingerprint(source)]
        if email:
            keys.append(operation + ":account:" + fingerprint(email))
        with self.store.db() as db, self.store.transaction(db):
            now = time.time()
            db.execute("DELETE FROM auth_attempts WHERE expires<=?", (now,))
            if db.execute("SELECT count(*) FROM auth_attempts").fetchone()[0] > 2046:
                raise RuntimeFault("quota_exceeded", "Authentication capacity exhausted")
            for key in keys:
                row = db.execute("SELECT count FROM auth_attempts WHERE key=?", (key,)).fetchone()
                if row and row[0] >= 5:
                    raise RuntimeFault("quota_exceeded", "Wait before trying authentication again")
            for key in keys:
                db.execute(
                    "INSERT INTO auth_attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1",
                    (key, now + 900),
                )
        return keys

    @contextmanager
    def _work(self, operation, source, email=""):
        if not PASSWORD_WORK.acquire(blocking=False):
            raise RuntimeFault("busy", "Authentication is busy")
        try:
            keys = self._reserve(operation, source, email)
            yield
            with self.store.db() as db, self.store.transaction(db):
                db.executemany("DELETE FROM auth_attempts WHERE key=?", [(key,) for key in keys])
        finally:
            PASSWORD_WORK.release()

    def _ticket_valid(self, db, kind, token):
        row = db.execute("SELECT digest,expires FROM auth_tickets WHERE kind=?", (kind,)).fetchone()
        if row and row["expires"] > time.time() and secrets.compare_digest(row["digest"], fingerprint(token)):
            return True
        legacy = db.execute("SELECT legacy_until FROM auth_control WHERE id=1").fetchone()[0]
        return (
            kind == "bootstrap"
            and legacy > time.time()
            and secrets.compare_digest(token.encode(), self.auth.owner.encode())
        )

    @staticmethod
    def _revoke(db):
        db.execute("UPDATE credentials SET revoked=1 WHERE kind='session'")
        db.execute("DELETE FROM auth_tickets")
        db.execute("UPDATE auth_control SET legacy_until=0")

    def setup(self, email, password, token, source):
        email, password = email_identifier(email), password_bytes(password, new=True)
        with self._work("bootstrap", source):
            with self.store.db() as db:
                if db.execute("SELECT 1 FROM administrator").fetchone() or not self._ticket_valid(
                    db, "bootstrap", token
                ):
                    raise RuntimeFault("unauthorized", "Setup credential is invalid or expired")
            encoded = hash_password(password)
            with self.store.db() as db, self.store.transaction(db):
                if db.execute("SELECT 1 FROM administrator").fetchone() or not self._ticket_valid(
                    db, "bootstrap", token
                ):
                    raise RuntimeFault("unauthorized", "Setup credential is invalid or expired")
                db.execute("INSERT INTO administrator VALUES(1,?,?,?,1)", (str(uuid4()), email, encoded))
                self._revoke(db)
                return self.auth._issue(db, kind="session", seconds=SESSION_SECONDS, generation=1)

    def login(self, email, password, source):
        email, password = email_identifier(email), password_bytes(password)
        with self._work("login", source, email):
            with self.store.db() as db:
                row = db.execute("SELECT * FROM administrator WHERE id=1").fetchone()
            # Same KDF work for unknown identifiers, and the same public failure.
            valid = (
                verify_password(password, row["password_hash"])
                if row
                else bool(hash_password(password)) and False
            )
            if not valid or row["email"] != email:
                raise RuntimeFault("unauthorized", "Invalid credentials")
            with self.store.db() as db, self.store.transaction(db):
                current = db.execute("SELECT generation FROM administrator WHERE id=1").fetchone()[0]
                if current != row["generation"]:
                    raise RuntimeFault("unauthorized", "Credentials changed")
                return self.auth._issue(db, kind="session", seconds=SESSION_SECONDS, generation=current)

    def recover(self, token, password, source):
        password = password_bytes(password, new=True)
        with self._work("recovery", source):
            with self.store.db() as db:
                if not self._ticket_valid(db, "recovery", token):
                    raise RuntimeFault("unauthorized", "Recovery credential is invalid or expired")
            encoded = hash_password(password)
            with self.store.db() as db, self.store.transaction(db):
                if not self._ticket_valid(db, "recovery", token):
                    raise RuntimeFault("unauthorized", "Recovery credential is invalid or expired")
                db.execute(
                    "UPDATE administrator SET password_hash=?,generation=generation+1 WHERE id=1", (encoded,)
                )
                self._revoke(db)
                db.execute("DELETE FROM auth_attempts")
        return {"status": "password_reset", "sign_in_required": True}

    def change_password(self, request, current_password, new_password, source):
        current_password, new_password = (
            password_bytes(current_password),
            password_bytes(new_password, new=True),
        )
        with self._work("change", source):
            principal = self.auth.require(request, owner=True)
            if principal["kind"] != "session" or principal.get("admin_generation") is None:
                raise RuntimeFault("forbidden", "Administrator session required")
            with self.store.db() as db:
                row = db.execute("SELECT * FROM administrator WHERE id=1").fetchone()
            if not verify_password(current_password, row["password_hash"]):
                raise RuntimeFault("unauthorized", "Invalid credentials")
            encoded = hash_password(new_password)
            with self.store.db() as db, self.store.transaction(db):
                # Recheck both session revocation and password epoch after KDF work.
                self.auth.require(request, owner=True)
                if (
                    db.execute("SELECT generation FROM administrator WHERE id=1").fetchone()[0]
                    != row["generation"]
                ):
                    raise RuntimeFault("unauthorized", "Credentials changed")
                db.execute(
                    "UPDATE administrator SET password_hash=?,generation=generation+1 WHERE id=1", (encoded,)
                )
                self._revoke(db)
        return {"status": "password_changed", "sign_in_required": True}
