"""Controlled loopback peer confirms that deadlines close actual response sockets."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.intel import McpClient


@contextmanager
def stalled_body_server():
    disconnected, entered = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body["method"] == "tools/call":
                self.send_response(200)
                self.send_header("Content-Length", "4096")
                self.end_headers()
                self.wfile.write(b" ")
                self.wfile.flush()
                entered.set()
                self.connection.settimeout(3)
                try:
                    if self.connection.recv(1) == b"":
                        disconnected.set()
                except ConnectionResetError:
                    disconnected.set()
                return
            result = json.dumps({"result": {}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", entered, disconnected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
        assert not thread.is_alive()


def test_deadline_closes_actual_socket_not_only_a_waiting_future(monkeypatch):
    monkeypatch.setenv("PALACE_MCP_LOOPBACK_HTTP_HOSTS", "127.0.0.1")
    with stalled_body_server() as (url, entered, disconnected):
        client = McpClient(name="local", url=url)
        with pytest.raises(TimeoutError):
            client.call_tool("kline", {}, deadline=time.monotonic() + 0.5)
        assert entered.is_set(), "the test must reach an open response body"
        assert disconnected.wait(1), "the peer must observe connection closure at the deadline"
