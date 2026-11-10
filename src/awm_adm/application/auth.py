"""Local owner bootstrap, revocable hashed tokens and CSRF-bound sessions."""

import hashlib
import secrets
import time
from uuid import uuid4

from ..runtime.protocol import RuntimeFault, dumps, loads


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Authority:
    def __init__(self, store, owner):
        self.store, self.owner = store, owner

    def issue(self, *, kind="token", adms=(), permissions=(), seconds=3600):
        with self.store.db() as db, self.store.transaction(db):
            return self._issue(db, kind=kind, adms=adms, permissions=permissions, seconds=seconds)

    def _issue(self, db, *, kind="token", adms=(), permissions=(), seconds=3600, generation=None):
        from .admin import csrf_for

        for adm in adms:
            self.store.info(adm)
        admin = db.execute("SELECT generation FROM administrator WHERE id=1").fetchone()
        if kind == "session" and admin and generation != admin[0]:
            raise RuntimeFault("unauthorized", "Password authentication required")
        secret = secrets.token_urlsafe(48)
        csrf = csrf_for(secret) if kind == "session" else None
        uid = str(uuid4())
        scope = {"adms": list(adms), "permissions": list(permissions)}
        db.execute("DELETE FROM credentials WHERE expires<=? OR revoked=1", (time.time(),))
        if db.execute("SELECT count(*) FROM credentials").fetchone()[0] >= 256:
            raise RuntimeFault("quota_exceeded", "Credential limit reached")
        db.execute(
            "INSERT INTO credentials(id,digest,kind,scope,csrf,expires,admin_generation) VALUES(?,?,?,?,?,?,?)",
            (
                uid,
                fingerprint(secret),
                kind,
                dumps(scope),
                fingerprint(csrf) if csrf else None,
                time.time() + seconds,
                generation,
            ),
        )
        return {"id": uid, "token": secret, "csrf": csrf, "expires_in": seconds}

    def authenticate(self, request):
        header = request.headers.get("authorization", "")
        bearer = header[7:] if header.startswith("Bearer ") else None
        cookie = request.cookies.get("awm_admin_session") or request.cookies.get("awm_session")
        token = bearer or cookie
        if not token or len(token) > 256:
            raise RuntimeFault("unauthorized", "Authentication required")
        with self.store.db() as db:
            admin = db.execute("SELECT generation FROM administrator WHERE id=1").fetchone()
            legacy = db.execute("SELECT legacy_until FROM auth_control WHERE id=1").fetchone()[0]
            if (
                bearer
                and admin is None
                and legacy > time.time()
                and secrets.compare_digest(token.encode(), self.owner.encode())
            ):
                return {"id": "owner", "owner": True, "kind": "owner"}
            row = db.execute(
                "SELECT * FROM credentials WHERE digest=? AND revoked=0 AND expires>?",
                (fingerprint(token), time.time()),
            ).fetchone()
        if row is None or (bearer and row["kind"] != "token") or (not bearer and row["kind"] != "session"):
            raise RuntimeFault("unauthorized", "Credential expired or invalid")
        if row["kind"] == "session" and (
            (admin is not None and row["admin_generation"] != admin[0])
            or (admin is None and legacy <= time.time())
        ):
            raise RuntimeFault("unauthorized", "Session is no longer authorized")
        if row["kind"] == "session" and request.method not in ("GET", "HEAD", "OPTIONS"):
            csrf = request.headers.get("x-csrf-token", "")
            if len(csrf) > 256 or not secrets.compare_digest(fingerprint(csrf), row["csrf"]):
                raise RuntimeFault("forbidden", "CSRF token required")
        return {
            "id": row["id"],
            "owner": row["kind"] == "session",
            "kind": row["kind"],
            "admin_generation": row["admin_generation"],
            **loads(row["scope"]),
        }

    def require(self, request, adm=None, permission="read", *, owner=False):
        principal = self.authenticate(request)
        if not principal["owner"] and (
            owner or adm not in principal["adms"] or permission not in principal["permissions"]
        ):
            raise RuntimeFault("forbidden", "Credential does not authorize this operation or ADM")
        return principal

    def revoke(self, uid):
        with self.store.db() as db:
            if not db.execute("UPDATE credentials SET revoked=1 WHERE id=?", (uid,)).rowcount:
                raise RuntimeFault("not_found", "Unknown credential")
