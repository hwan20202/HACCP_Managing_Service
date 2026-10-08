"""Regression coverage for slow or unavailable reverse DNS on CI runners."""

import json
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from django.core.servers.basehttp import WSGIRequestHandler

from scripts.smoke_server import LoopbackWSGIServer


class SmokeServerTests(unittest.TestCase):
    def test_http_works_without_reverse_dns(self):
        def application(environ, start_response):
            body = json.dumps(
                {"name": environ["SERVER_NAME"], "port": environ["SERVER_PORT"]}
            ).encode()
            start_response(
                "200 OK", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
            )
            return [body]

        with patch("socket.getfqdn", side_effect=AssertionError("Reverse DNS must not be used")):
            with LoopbackWSGIServer(("127.0.0.1", 0), WSGIRequestHandler) as server:
                server.set_app(application)
                server.timeout = 2
                worker = threading.Thread(target=server.handle_request, daemon=True)
                worker.start()
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                try:
                    connection.request("GET", "/")
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(
                        json.loads(response.read()),
                        {"name": "127.0.0.1", "port": str(server.server_port)},
                    )
                finally:
                    connection.close()
                    worker.join(timeout=3)
                self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
