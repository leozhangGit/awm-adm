"""Authenticated private operator CLI; separate from the public application API."""

import argparse
import json
import sys
import tempfile
import urllib.error
from pathlib import Path

from ..engine.snapshots import MAX_ARCHIVE_BYTES, read_snapshot
from .component import exchange
from .http import secret
from .protocol import pack


def main(argv=None):
    parser = argparse.ArgumentParser(prog="awm-adm operator")
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--token-file", type=Path, default=Path("/run/secrets/owner-token"))
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("list")
    create = commands.add_parser("create")
    create.add_argument("name")
    create.add_argument("--mode", choices=("forward", "backward"), default="backward")
    create.add_argument("--snapshot", type=Path)
    for op in ("info", "capabilities", "query", "run"):
        command = commands.add_parser(op)
        command.add_argument("instance")
        if op == "query":
            command.add_argument(
                "--input", type=Path, help="JSON containing query and optional limits; stdin by default"
            )
        if op == "run":
            command.add_argument("run_id")
    args = parser.parse_args(argv)
    base = args.url + "/internal/m2/adms"
    body = None
    if args.operation == "create":
        body = {"name": args.name, "mode": args.mode}
        if args.snapshot:
            if str(args.snapshot) == "-":
                raw = sys.stdin.buffer.read(MAX_ARCHIVE_BYTES + 1)
                if len(raw) > MAX_ARCHIVE_BYTES:
                    raise ValueError("Snapshot exceeds archive byte limit")
                with tempfile.TemporaryDirectory(prefix="awm-adm-import-") as directory:
                    path = Path(directory) / "model.adm"
                    path.write_bytes(raw)
                    body["snapshot"] = pack(read_snapshot(path))
            else:
                body["snapshot"] = pack(read_snapshot(args.snapshot))
    elif args.operation != "list":
        from .storage import identifier

        base += "/" + identifier(args.instance)
        if args.operation in ("query", "capabilities"):
            base += "/compute"
            if args.operation == "capabilities":
                body = {"query": {"op": "capabilities"}}
            else:
                raw = args.input.read_bytes() if args.input else sys.stdin.buffer.read(2_097_153)
                if len(raw) > 2_097_152:
                    raise ValueError("Operator input exceeds body limit")
                body = json.loads(raw)
        elif args.operation == "run":
            base += "/runs/" + identifier(args.run_id)
    try:
        timeout = max(15, (body or {}).get("limits", {}).get("max_duration_ms", 10000) / 1000 + 5)
        print(json.dumps(exchange(base, secret(args.token_file), body, timeout=timeout), indent=2))
    except urllib.error.HTTPError as error:
        print(json.dumps({"status": error.code, "detail": json.loads(error.read(65_536))}))
        return 1
    return 0
