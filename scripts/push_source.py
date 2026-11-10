"""Push an immutable JSON batch to one already authorized source queue.

AWM_ADM_APPEND_TOKEN holds the short-lived append-only credential. --batch is
an AppendInput JSON file with a durable idempotency_key, reused after uncertainty.
No automatic retry, provider configuration, policy changes or local token storage.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from awm_adm.intake.models import AppendInput


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="Exact push URL shown by Teach")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--batch", type=Path)
    choice.add_argument("--receipt", help="Original batch idempotency_key to look up its receipt")
    args = parser.parse_args()
    endpoint = urllib.parse.urlsplit(args.endpoint)
    if (
        endpoint.scheme not in {"http", "https"}
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
    ):
        parser.error("Use the exact HTTP(S) push endpoint without credentials or query parameters")
    if endpoint.scheme == "http" and endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Plain HTTP is supported only on loopback; use HTTPS remotely")
    if not endpoint.path.endswith("/push"):
        parser.error("Expected an intake push endpoint")
    token = os.environ.get("AWM_ADM_APPEND_TOKEN")
    if not token:
        parser.error("Set AWM_ADM_APPEND_TOKEN to the issued append-only credential")
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    url = args.endpoint
    payload = None
    if args.batch:
        if args.batch.stat().st_size > 2097152:
            parser.error("Batch file exceeds 2 MiB")
        body = AppendInput.model_validate_json(args.batch.read_bytes())
        payload = body.model_dump_json().encode()
    else:
        url = url.removesuffix("/push") + "/receipts/" + urllib.parse.quote(args.receipt, safe="")

    # Redirects must never forward a credential to a different destination.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(urllib.request.Request(url, payload, headers), timeout=15) as response:
            result = json.loads(response.read(1048576))
        print(json.dumps(result, indent=2))
    except urllib.error.HTTPError as error:
        print(
            f"HTTP {error.code}: no automatic retry. Preserve the batch's idempotency key.", file=sys.stderr
        )
        print(error.read(16384).decode(errors="replace"), file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError):
        print(
            "Acknowledgement unknown. Retry the identical batch and credential; do not create a new identity.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
