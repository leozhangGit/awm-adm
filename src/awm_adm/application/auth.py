"""Hashed, expiring append-only queue credentials; never workspace login."""

import hashlib
import secrets
import time
from uuid import uuid4

from ..runtime.protocol import RuntimeFault, dumps, loads


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AppendAuthority:
    def __init__(self, store):
        self.store = store

    def issue(self, *, adms, seconds=3600):
        with self.store.db() as db, self.store.transaction(db):
            return self._issue(db, adms=adms, permissions=["append"], seconds=seconds)

    def _issue(self, db, *, adms, permissions, seconds):
        if permissions != ["append"] or not 0 < seconds <= 86400:
            raise RuntimeFault("forbidden", "Only bounded queue append credentials are supported")
        for adm in adms:
            self.store.info(adm)
        secret = secrets.token_urlsafe(48)
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
                "token",
                dumps(scope),
                None,
                time.time() + seconds,
                None,
            ),
        )
        return {"id": uid, "token": secret, "csrf": None, "expires_in": seconds}

    def authenticate(self, request):
        header = request.headers.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else None
        if not token or len(token) > 256:
            raise RuntimeFault("unauthorized", "Authentication required")
        with self.store.db() as db:
            row = db.execute(
                "SELECT * FROM credentials WHERE digest=? AND revoked=0 AND expires>?",
                (fingerprint(token), time.time()),
            ).fetchone()
        if row is None or row["kind"] != "token":
            raise RuntimeFault("unauthorized", "Credential expired or invalid")
        return {
            "id": row["id"],
            "owner": False,
            "kind": row["kind"],
            "admin_generation": row["admin_generation"],
            **loads(row["scope"]),
        }

    def require(self, request, adm):
        principal = self.authenticate(request)
        if adm not in principal["adms"] or principal["permissions"] != ["append"]:
            raise RuntimeFault("forbidden", "Credential does not authorize this operation or ADM")
        return principal
