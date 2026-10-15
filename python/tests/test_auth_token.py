"""One server token (Crowkis 0.5.2): the admin client sends it as Bearer, `api_key`
still works as a deprecated alias, the RESP client accepts `token=`, and the
value never shows up in an error, a warning or a repr."""

import socket
import threading
import unittest
import warnings
from http.server import BaseHTTPRequestHandler, HTTPServer

from crowkis import client as client_mod
from crowkis.client import CrowkisAdmin, CrowkisClient, CrowkisError

SECRET = "tok-7f3a-very-secret"


class _Http:
    """A local HTTP server that records request headers and answers `status`."""

    def __init__(self, status=200, body=b'{"ok":true}'):
        seen = self.headers = []

        class Handler(BaseHTTPRequestHandler):
            def _answer(self):
                seen.append({k.lower(): v for k, v in self.headers.items()})
                length = int(self.headers.get("content-length") or 0)
                self.rfile.read(length)
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PUT = _answer

            def log_message(self, *_):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class AdminTokenTests(unittest.TestCase):
    def setUp(self):
        client_mod._API_KEY_WARNED = False

    def test_token_goes_out_as_bearer(self):
        http = _Http()
        try:
            CrowkisAdmin(http.url, token=SECRET).flush_tenant("acme")
        finally:
            http.close()
        self.assertEqual(http.headers[0].get("authorization"), f"Bearer {SECRET}")
        self.assertNotIn("x-crowkis-api-key", http.headers[0])

    def test_no_token_sends_no_authorization(self):
        http = _Http()
        try:
            CrowkisAdmin(http.url).health()
        finally:
            http.close()
        self.assertNotIn("authorization", http.headers[0])

    def test_api_key_still_sends_x_crowkis_api_key_and_warns_once(self):
        http = _Http()
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                CrowkisAdmin(http.url, api_key=SECRET).health()
                CrowkisAdmin(http.url, api_key=SECRET).health()
        finally:
            http.close()
        self.assertEqual([h.get("x-crowkis-api-key") for h in http.headers], [SECRET] * 2)
        self.assertEqual([h.get("authorization") for h in http.headers], [None] * 2)
        deprecations = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        self.assertEqual(len(deprecations), 1)
        self.assertIn("token=", str(deprecations[0].message))
        self.assertNotIn(SECRET, str(deprecations[0].message))

    def test_token_wins_over_api_key(self):
        http = _Http()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                CrowkisAdmin(http.url, token=SECRET, api_key="old").health()
        finally:
            http.close()
        self.assertEqual(http.headers[0].get("authorization"), f"Bearer {SECRET}")
        self.assertNotIn("x-crowkis-api-key", http.headers[0])

    def test_token_never_in_error_or_repr(self):
        http = _Http(status=401, body=b'{"error":"missing or wrong token"}')
        admin = CrowkisAdmin(http.url, token=SECRET)
        try:
            with self.assertRaises(CrowkisError) as ctx:
                admin.flush_tenant("acme")
        finally:
            http.close()
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertNotIn(SECRET, repr(ctx.exception))
        self.assertNotIn(SECRET, repr(admin))
        self.assertNotIn(SECRET, str(admin))

    def test_a_token_with_a_line_break_is_refused_without_echoing_it(self):
        with self.assertRaises(CrowkisError) as ctx:
            CrowkisAdmin("http://127.0.0.1:1", token=SECRET + "\r\nx-evil: 1").health()
        self.assertNotIn(SECRET, str(ctx.exception))


class RespTokenTests(unittest.TestCase):
    def _first_frames(self, **kwargs):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        received = bytearray()

        def serve():
            conn, _ = listener.accept()
            with conn:
                while received.count(b"PING") == 0:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    received.extend(chunk)
                    conn.sendall(b"+OK\r\n" * chunk.count(b"*"))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        client = CrowkisClient(port=listener.getsockname()[1], max_retries=0, **kwargs)
        try:
            client.execute("PING")
        finally:
            client.close()
            thread.join(2)
            listener.close()
        return bytes(received), client

    def test_token_is_sent_as_auth(self):
        frames, client = self._first_frames(token=SECRET)
        self.assertTrue(frames.startswith(b"*2\r\n$4\r\nAUTH\r\n"))
        self.assertIn(SECRET.encode(), frames)
        self.assertNotIn(SECRET, repr(client))

    def test_auth_token_still_works(self):
        frames, _ = self._first_frames(auth_token=SECRET)
        self.assertTrue(frames.startswith(b"*2\r\n$4\r\nAUTH\r\n"))
        self.assertIn(SECRET.encode(), frames)

    def test_no_token_sends_no_auth(self):
        frames, _ = self._first_frames()
        self.assertNotIn(b"AUTH", frames)


if __name__ == "__main__":
    unittest.main()
