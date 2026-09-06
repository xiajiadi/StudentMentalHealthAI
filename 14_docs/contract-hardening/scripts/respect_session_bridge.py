"""Loopback-only Respect session bridge for synthetic closure runs.

The bridge keeps the upstream Set-Cookie attributes intact in the response,
but forwards only the cookie name/value pair held in its in-memory jar. It is
not part of the application runtime and must never be used as a production
proxy.
"""

from __future__ import annotations

import argparse
import http.client
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


_HOP_BY_HOP = {
    "connection",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class SessionJar:
    def __init__(self) -> None:
        self._cookies: dict[str, str] = {}
        self._lock = threading.Lock()

    def update_from_headers(self, headers: list[tuple[str, str]]) -> None:
        cookie = SimpleCookie()
        for name, value in headers:
            if name.lower() == "set-cookie":
                cookie.load(value)
        with self._lock:
            for morsel in cookie.values():
                self._cookies[morsel.key] = morsel.value

    def header_value(self) -> str | None:
        with self._lock:
            if not self._cookies:
                return None
            return "; ".join(
                f"{name}={value}" for name, value in sorted(self._cookies.items())
            )


class BridgeServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, upstream: str) -> None:
        super().__init__(server_address, handler_class)
        parsed = urlsplit(upstream)
        if parsed.scheme != "http" or not parsed.hostname or parsed.path not in {"", "/"}:
            raise ValueError("the closure bridge requires an http upstream origin")
        self.upstream_host = parsed.hostname
        self.upstream_port = parsed.port or 80
        self.upstream_prefix = ""
        self.session_jar = SessionJar()


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, format: str, *args) -> None:
        del format, args

    def do_GET(self) -> None:  # noqa: N802
        self._forward()

    def do_POST(self) -> None:  # noqa: N802
        self._forward()

    def _forward(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else None
        if self.command == "POST" and self.path.endswith("/complete") and body is None:
            body = b"{}"
        headers: dict[str, str] = {}
        for name, value in self.headers.items():
            if name.lower() in _HOP_BY_HOP or name.lower() in {"host", "cookie"}:
                continue
            headers[name] = value
        cookie = self.server.session_jar.header_value()  # type: ignore[attr-defined]
        if cookie:
            headers["Cookie"] = cookie
        if body is not None:
            headers["Content-Length"] = str(len(body))

        connection = http.client.HTTPConnection(
            self.server.upstream_host,  # type: ignore[attr-defined]
            self.server.upstream_port,  # type: ignore[attr-defined]
            timeout=30,
        )
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            response_headers = response.getheaders()
            response_body = response.read()
        finally:
            connection.close()

        self.server.session_jar.update_from_headers(response_headers)  # type: ignore[attr-defined]
        self.send_response(response.status, response.reason)
        for name, value in response_headers:
            if name.lower() not in _HOP_BY_HOP:
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(response_body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", default="http://127.0.0.1:8080")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    server = BridgeServer(("127.0.0.1", args.port), BridgeHandler, args.upstream)
    print(f"respect_session_bridge listening on 127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
