"""OpenHost auth proxy for Hermes Agent.

Sits between the OpenHost router and Hermes's dashboard on loopback.
The owner is auto-authenticated; all other traffic is blocked.

Pattern: simple reverse proxy that checks X-OpenHost-Is-Owner on every
request and proxies to the upstream dashboard if the owner is verified.
"""

from __future__ import annotations

import http.client
import logging
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import AbstractSet, Iterable

OWNER_HEADER = "X-OpenHost-Is-Owner"

HOP_BY_HOP = frozenset(
    h.lower()
    for h in (
        "Connection", "Keep-Alive", "Proxy-Authenticate",
        "Proxy-Authorization", "TE", "Trailer",
        "Transfer-Encoding", "Upgrade", "Host", "Content-Length",
    )
)

STRIP_HEADERS = frozenset(h.lower() for h in (OWNER_HEADER, "X-OpenHost-User"))

MAX_BODY = 100 * 1024 * 1024
HEALTHZ_PATH = "/_healthz"

logging.basicConfig(
    level=os.environ.get("AUTH_PROXY_LOG_LEVEL", "INFO"),
    format="[auth-proxy] %(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("auth_proxy")


def _strip(headers: Iterable[tuple[str, str]], drop: AbstractSet[str]) -> list[tuple[str, str]]:
    d = {h.lower() for h in drop}
    return [(k, v) for k, v in headers if k.lower() not in d]


class Handler(BaseHTTPRequestHandler):
    upstream_host = "127.0.0.1"
    upstream_port = 9119

    def log_message(self, fmt, *args):
        path = getattr(self, "path", "")
        if path == HEALTHZ_PATH:
            return
        log.info("%s - " + fmt, self.address_string(), *args)

    def do_GET(self): self._dispatch()
    def do_HEAD(self): self._dispatch()
    def do_POST(self): self._dispatch()
    def do_PUT(self): self._dispatch()
    def do_DELETE(self): self._dispatch()
    def do_PATCH(self): self._dispatch()
    def do_OPTIONS(self): self._dispatch()

    def _dispatch(self):
        path = self.path or "/"

        if path == HEALTHZ_PATH or path.startswith(HEALTHZ_PATH + "?"):
            body = b"ok\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return

        is_owner = self.headers.get(OWNER_HEADER, "").lower() == "true"

        if not is_owner:
            self.send_error(403, "Owner authentication required")
            return

        self._proxy()

    def _proxy(self):
        cleaned = _strip(self.headers.items(), HOP_BY_HOP | STRIP_HEADERS)
        fwd_host = self.headers.get("X-Forwarded-Host", "").strip()
        cleaned.append(("Host", fwd_host or f"{self.upstream_host}:{self.upstream_port}"))

        body = None
        cl = self.headers.get("Content-Length")
        if cl:
            try:
                length = int(cl)
            except ValueError:
                self.send_error(400, "bad Content-Length")
                return
            if 0 < length <= MAX_BODY:
                body = self.rfile.read(length)
            elif length > MAX_BODY:
                self.send_error(413, "too large")
                return
            else:
                body = b""
        elif self.command in ("POST", "PUT", "PATCH", "DELETE"):
            body = b""

        conn = http.client.HTTPConnection(self.upstream_host, self.upstream_port, timeout=120)
        try:
            conn.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for k, v in cleaned:
                conn.putheader(k, v)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(message_body=body)
            upstream = conn.getresponse()

            payload = upstream.read(MAX_BODY + 1)
            if len(payload) > MAX_BODY:
                self.send_error(502, "upstream too large")
                return

            self.send_response(upstream.status, upstream.reason or "")
            for k, v in upstream.getheaders():
                if k.lower() in HOP_BY_HOP:
                    continue
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except (OSError, http.client.HTTPException) as e:
            log.warning("upstream error: %s", e)
            self.send_error(502, "Bad Gateway")
        finally:
            conn.close()


class Server(ThreadingHTTPServer):
    address_family = socket.AF_INET
    allow_reuse_address = True
    daemon_threads = True


def main():
    listen_port = int(os.environ.get("AUTH_PROXY_LISTEN_PORT", "8080"))
    Handler.upstream_host = os.environ.get("AUTH_PROXY_UPSTREAM_HOST", "127.0.0.1")
    Handler.upstream_port = int(os.environ.get("AUTH_PROXY_UPSTREAM_PORT", "9119"))

    server = Server(("0.0.0.0", listen_port), Handler)
    log.info("listening on 0.0.0.0:%d -> %s:%d", listen_port, Handler.upstream_host, Handler.upstream_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
