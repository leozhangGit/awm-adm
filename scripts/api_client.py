"""Standard-library example client for the local API; no awm_adm imports required."""

import argparse
import getpass
import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="API path such as /api/v1/adms")
    parser.add_argument("--method", default="GET", choices=["GET", "POST", "PUT", "PATCH", "DELETE"])
    parser.add_argument("--body", type=Path, help="UTF-8 JSON file; omit for no body")
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument("--token-file", type=Path, help="Explicit scoped API credential file")
    auth.add_argument(
        "--login",
        action="store_true",
        help="Prompt locally for administrator email/password; session stays in memory",
    )
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--events", action="store_true", help="Read one bounded SSE connection")
    args = parser.parse_args()
    url = urllib.parse.urlsplit(args.url)
    if (
        url.scheme != "http"
        or url.hostname not in ("127.0.0.1", "localhost", "::1")
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        parser.error("This example sends the local token only to a loopback HTTP service")
    if not args.path.startswith("/api/v1/") or args.path.startswith("//"):
        parser.error("Use an /api/v1/ path")
    body = args.body.read_bytes() if args.body else None
    if body and len(body) > 2_097_152:
        parser.error("Body exceeds 2 MiB")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    headers = {"Content-Type": "application/json"}
    if args.login:
        print("Administrator email: ", end="", file=sys.stderr, flush=True)
        email = input().strip()
        password = getpass.getpass("Password: ")
        payload = json.dumps({"email": email, "password": password}).encode()
        try:
            with opener.open(
                urllib.request.Request(
                    args.url.rstrip("/") + "/api/v1/auth/login", data=payload, headers=headers, method="POST"
                ),
                timeout=20,
            ) as response:
                issued = json.load(response)
            headers["X-CSRF-Token"] = issued["csrf"]
        except urllib.error.HTTPError:
            print("Authentication failed or temporarily limited", file=sys.stderr)
            return 1
        finally:
            password = payload = None
    else:
        headers["Authorization"] = "Bearer " + args.token_file.read_text().strip()
    if args.events:
        headers["Accept"] = "text/event-stream"
    request = urllib.request.Request(
        args.url.rstrip("/") + args.path, data=body, headers=headers, method=args.method
    )
    try:
        with opener.open(request, timeout=20) as response:
            if args.events:
                for line in response:
                    sys.stdout.write(line.decode())
            else:
                print(json.dumps(json.load(response), indent=2))
    except urllib.error.HTTPError as error:
        print(error.read(65_536).decode(), file=sys.stderr)
        return 1
    finally:
        if args.login:
            try:
                opener.open(
                    urllib.request.Request(
                        args.url.rstrip("/") + "/api/v1/auth/logout",
                        data=b"{}",
                        headers=headers,
                        method="POST",
                    ),
                    timeout=10,
                ).close()
            except (OSError, ValueError):
                pass  # Session retains its server-side expiry if logout cannot reach the service.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
