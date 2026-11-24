"""Locally measured failures, with fixed codes and no exception/body disclosure."""

import http.client
import socket
import ssl
import time


class TransportFailure(Exception):
    def __init__(self, reason, stage, http_status=None):
        self.reason, self.stage, self.http_status = reason, stage, http_status
        super().__init__("Provider transport failed")


def reason(error):
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, socket.gaierror):
        return "dns"
    if isinstance(error, ssl.SSLError):
        return "tls"
    if isinstance(error, ConnectionError):
        return "connection"
    if isinstance(error, http.client.HTTPException):
        return "http_protocol"
    if isinstance(error, OSError):
        return "connection"
    return "transport_error"


def measured(outcome, started, timeout):
    diagnostics = dict(outcome.get("diagnostics") or {})
    diagnostics.update(
        elapsed_ms=min(86_400_000, max(0, round((time.monotonic() - started) * 1000))),
        timeout_ms=min(600_000, max(0, round(timeout * 1000))),
    )
    return {**outcome, "diagnostics": diagnostics}


def uncertain(reason, stage, *, http_status=None, child_exit_code=None):
    diagnostics = {"transport_failure": reason, "failure_stage": stage}
    if http_status is not None:
        diagnostics["http_status"] = http_status
    if child_exit_code is not None and -65536 <= child_exit_code <= 65536:
        diagnostics["child_exit_code"] = child_exit_code
    return {
        "status": "outcome_unknown",
        "error": "provider_timeout" if reason == "timeout" else "transport_uncertain",
        "usage": None,
        "text": None,
        "diagnostics": diagnostics,
    }
