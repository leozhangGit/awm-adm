"""Real loopback HTTP transport; no provider and no ambient proxy or credentials."""

import json
import os
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from uuid import uuid4

from awm_adm_plugin.client import Client, Problem


class TransportTests(unittest.TestCase):
    def test_explicit_invalid_port_is_not_replaced_by_default(self):
        with self.assertRaises(Problem) as error:
            Client("http://127.0.0.1:0")
        self.assertEqual(error.exception.code, "invalid_endpoint")
        self.assertEqual(Client("http://127.0.0.1").port, 9527)

    def test_real_requests_refuse_redirects_and_preserve_uncertain_server_failure(self):
        seen = []
        response = {
            "status": 200,
            "body": {
                "local_service": {
                    "profile": "awm-adm-local/1",
                    "installation_id": str(uuid4()),
                    "connection_ready": False,
                }
            },
        }

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append((self.path, dict(self.headers)))
                raw = json.dumps(response["body"]).encode()
                self.send_response(response["status"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Location", "http://example.invalid/")
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            c = Client(f"http://localhost:{server.server_port}")
            with patch.dict(
                os.environ,
                {"HTTP_PROXY": "http://example.invalid:1", "ALL_PROXY": "http://example.invalid:1"},
            ):
                self.assertIs(c.system()["connection_ready"], False)
            self.assertEqual(seen[0][0], "/api/v1/system")
            self.assertNotIn("Authorization", seen[0][1])
            self.assertNotIn("Cookie", seen[0][1])
            for status, expected in [(302, "redirect_refused"), (500, "service_unavailable")]:
                response["status"] = status
                with self.assertRaises(Problem) as error:
                    c.system()
                self.assertEqual(error.exception.code, expected)
            self.assertEqual(len(seen), 3)  # No followed redirect or hidden retry.
            with patch(
                "socket.getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 9527))],
            ):
                with self.assertRaises(Problem) as error:
                    c.system()
                self.assertEqual(error.exception.code, "invalid_endpoint")
            self.assertEqual(len(seen), 3)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_wrong_protocol_cannot_enable_work(self):
        c = Client()
        for local in [
            None,
            {},
            {"profile": "awm-adm-local/1", "installation_id": str(uuid4()), "connection_ready": "true"},
        ]:
            with (
                patch.object(c, "_request", return_value={"local_service": local}),
                self.assertRaises(Problem),
            ):
                c.system()
