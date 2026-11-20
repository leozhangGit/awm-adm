"""Shared trusted-local-workspace access. No user authentication or credential issuance."""

import ipaddress
import socket
import struct
from pathlib import Path

from ..runtime.protocol import RuntimeFault
from .auth import AppendAuthority


class LocalWorkspace:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            self.identity = db.execute("SELECT identity FROM local_workspace WHERE id=1").fetchone()[0]

    def authenticate(self, request):
        # HTTP locality/origin checks run before handlers. This is an internal actor,
        # not an authenticated human or proof that a client label is truthful.
        return {"id": "workspace:" + self.identity, "owner": True, "kind": "local_workspace"}

    def require(self, request, adm=None, permission="read", *, owner=False):
        if permission == "append" and request.headers.get("authorization"):
            return AppendAuthority(self.store).require(request, adm)
        return self.authenticate(request)

    def _issue(self, db, *, adms, permissions, seconds):
        # Retained append-producer capability; never a workspace login credential.
        if permissions != ["append"]:
            raise RuntimeFault("forbidden", "Only queue append credentials are supported")
        return AppendAuthority(self.store)._issue(db, adms=adms, permissions=permissions, seconds=seconds)


def local_peer(peer, ingress):
    if peer == "testclient":
        return True  # In-process ASGI test transport, never a TCP peer address.
    try:
        return ipaddress.ip_address(peer).is_loopback or peer in ingress
    except ValueError:
        return False


def docker_ingress():
    """Exact default-route gateway for the supported Docker loopback publication.

    This does not attest to host publication settings. The host deployment preflight
    checks those; no private subnet or forwarded-header fallback is allowed.
    """
    routes = Path("/proc/net/route").read_text().splitlines()[1:]
    gateways = set()
    for line in routes:
        fields = line.split()
        if len(fields) >= 4 and fields[1] == "00000000" and int(fields[3], 16) & 2:
            gateways.add(socket.inet_ntoa(struct.pack("<I", int(fields[2], 16))))
    if len(gateways) != 1:
        raise RuntimeFault("invalid_input", "Supported Docker ingress requires one default gateway")
    return gateways
