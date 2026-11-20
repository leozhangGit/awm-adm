"""Fixed local-service transport. No credentials, redirects, proxies or generic tool."""

import http.client
import ipaddress
import json
import socket
from urllib.parse import urlencode, urlsplit
from uuid import UUID


class Problem(Exception):
    def __init__(self, code, summary):
        self.code, self.summary = code, summary
        super().__init__(summary)


def identifier(value):
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise Problem("invalid_identity", "The service identity is not valid.") from None
    return value


class Client:
    def __init__(self, url="http://127.0.0.1:9527"):
        try:
            parsed = urlsplit(url)
            port = 9527 if parsed.port is None else parsed.port
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or not 1024 <= port <= 65535
            ):
                raise ValueError
            host = parsed.hostname
            self.origin = f"http://{'[' + host + ']' if ':' in host else host}:{port}"
            self.host, self.port = host, port
        except (ValueError, TypeError):
            raise Problem(
                "invalid_endpoint", "Use a loopback AWM-ADM URL, normally http://127.0.0.1:9527."
            ) from None

    def _request(self, method, path, body=None, revision=None):
        try:
            addresses = {a[4][0] for a in socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)}
            if not addresses or not all(ipaddress.ip_address(a).is_loopback for a in addresses):
                raise Problem("invalid_endpoint", "The configured service did not resolve only to loopback.")
            address = "127.0.0.1" if "127.0.0.1" in addresses else sorted(addresses)[0]
            connection = http.client.HTTPConnection(address, self.port, timeout=5)
            headers = {
                "Host": self.origin[7:],
                "Accept": "application/json",
                "X-AWM-ADM-Client": "codex-local/1",
            }
            raw = None if body is None else json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            if raw is not None:
                headers["Content-Type"] = "application/json"
                if len(raw) > 1_048_576:
                    raise Problem("input_too_large", "Use a smaller, focused message.")
            if revision is not None:
                headers["If-Match"] = identifier(revision)
            try:
                connection.request(method, "/api/v1" + path, body=raw, headers=headers)
                response = connection.getresponse()
                if response.status >= 500:
                    raise Problem(
                        "service_unavailable",
                        "The service failed to acknowledge this operation. Retain its identity before recovery.",
                    )
                if 300 <= response.status < 400:
                    raise Problem(
                        "redirect_refused", "AWM-ADM redirected the request; the plugin will not follow it."
                    )
                data = response.read(4_194_305)
                if len(data) > 4_194_304:
                    raise Problem("response_too_large", "The service response exceeded the connector limit.")
                if "application/json" not in response.getheader("Content-Type", ""):
                    raise Problem(
                        "incompatible_service", "The endpoint did not return the AWM-ADM JSON protocol."
                    )
                value = json.loads(data)
                if not isinstance(value, dict):
                    raise ValueError
                if response.status >= 400:
                    code = value.get("code")
                    safe = {
                        "gone",
                        "not_found",
                        "stale_context",
                        "conflict",
                        "remote_calls_disabled",
                        "invalid_input",
                        "quota_exceeded",
                        "forbidden",
                        "not_ready",
                    }
                    code = code if code in safe else "service_error"
                    raise Problem(
                        code,
                        {
                            "gone": "The bound model has been deleted. Choose a model explicitly before continuing.",
                            "stale_context": "The model changed. Review its current state before starting new work.",
                            "remote_calls_disabled": "Enable the connection in the AWM-ADM console to use Ask or Teach.",
                        }.get(code, f"AWM-ADM could not complete this request ({code})."),
                    )
                return value
            finally:
                connection.close()
        except Problem:
            raise
        except (OSError, http.client.HTTPException):
            raise Problem(
                "service_unavailable",
                "AWM-ADM is unavailable. Retained work can be checked when it returns; do not invent a fresh submission.",
            ) from None
        except (ValueError, UnicodeError):
            raise Problem(
                "incompatible_service", "The service returned an invalid protocol response."
            ) from None

    def system(self):
        value = self._request("GET", "/system").get("local_service")
        if not isinstance(value, dict) or value.get("profile") != "awm-adm-local/1":
            raise Problem(
                "incompatible_service", "This plugin requires the login-free AWM-ADM local service."
            )
        identifier(value.get("installation_id"))
        if type(value.get("connection_ready")) is not bool:
            raise Problem("incompatible_service", "The service readiness contract is invalid.")
        return value

    def model(self, key):
        return self._request("GET", "/adms/" + identifier(key))

    def create(self, name, identity):
        return self._request("POST", "/adms", {"name": name, "mode": "backward", "idempotency_key": identity})

    def operation(self, key):
        return self._request("GET", "/operations/" + identifier(key))

    def submit(self, model, channel, body, revision):
        if channel not in {"ask", "teach"}:
            raise Problem("invalid_channel", "Use Ask or Teach.")
        return self._request("POST", f"/adms/{identifier(model)}/{channel}", body, revision)

    def interaction(self, model, key, *, cancel=False):
        return self._request(
            "POST" if cancel else "GET",
            f"/adms/{identifier(model)}/interactions/{identifier(key)}" + ("/cancel" if cancel else ""),
        )

    def mode(self, model, mode, epoch):
        if mode not in {"forward", "backward"} or type(epoch) is not int:
            raise Problem("invalid_mode", "Choose forward or backward explicitly.")
        return self._request(
            "PATCH", f"/adms/{identifier(model)}/settings", {"mode": mode, "expected_epoch": epoch}
        )

    def knowledge(self, model, query="", after=0, revision=None):
        params = {"query": query, "after": after, "limit": 20}
        if revision:
            params["revision"] = identifier(revision)
        return self._request("GET", f"/adms/{identifier(model)}/knowledge?" + urlencode(params))

    def request_record(self, model, key):
        return self._request("GET", f"/adms/{identifier(model)}/requests/{identifier(key)}")
