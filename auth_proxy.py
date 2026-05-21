"""OpenHost auth proxy for Hermes Agent.

Handles both regular HTTP and WebSocket upgrade requests. Owner auth is
checked via X-OpenHost-Is-Owner header on every request. WebSocket
connections are tunneled as raw TCP after the upgrade handshake.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

OWNER_HEADER = "X-OpenHost-Is-Owner"
STRIP_HEADERS = frozenset(h.lower() for h in (OWNER_HEADER, "X-OpenHost-User"))
HEALTHZ_PATH = "/_healthz"
BUF_SIZE = 65536

logging.basicConfig(
    level=os.environ.get("AUTH_PROXY_LOG_LEVEL", "INFO"),
    format="[auth-proxy] %(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("auth_proxy")


def _parse_headers(raw: bytes) -> tuple[str, str, dict[str, str], bytes]:
    head, _, rest = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    request_line = lines[0].decode("latin-1")
    parts = request_line.split(" ", 2)
    method = parts[0] if len(parts) > 0 else "GET"
    path = parts[1] if len(parts) > 1 else "/"
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if b":" not in line:
            continue
        k, v = line.split(b":", 1)
        headers[k.strip().decode("latin-1").lower()] = v.strip().decode("latin-1")
    return method, path, headers, rest


def _rebuild_request(method: str, path: str, headers: dict[str, str], body: bytes, upstream_host: str, upstream_port: int) -> bytes:
    fwd_host = headers.get("x-forwarded-host", f"{upstream_host}:{upstream_port}")
    lines = [f"{method} {path} HTTP/1.1"]
    for k, v in headers.items():
        kl = k.lower()
        if kl in STRIP_HEADERS or kl == "host":
            continue
        lines.append(f"{k}: {v}")
    lines.append(f"Host: {fwd_host}")
    header_block = "\r\n".join(lines) + "\r\n\r\n"
    return header_block.encode("latin-1") + body


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        while True:
            data = await reader.read(BUF_SIZE)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle_client(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter, upstream_host: str, upstream_port: int):
    try:
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = await asyncio.wait_for(client_reader.read(BUF_SIZE), timeout=30)
            if not chunk:
                client_writer.close()
                return
            raw += chunk

        head_end = raw.index(b"\r\n\r\n") + 4
        header_bytes = raw[:head_end]
        leftover = raw[head_end:]

        method, path, headers, _ = _parse_headers(header_bytes)

        if path == HEALTHZ_PATH or path.startswith(HEALTHZ_PATH + "?"):
            resp = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 3\r\nConnection: close\r\n\r\nok\n"
            client_writer.write(resp)
            await client_writer.drain()
            client_writer.close()
            return

        is_owner = headers.get(OWNER_HEADER.lower(), "").lower() == "true"
        if not is_owner:
            resp = b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nContent-Length: 30\r\nConnection: close\r\n\r\nOwner authentication required\n"
            client_writer.write(resp)
            await client_writer.drain()
            client_writer.close()
            return

        is_websocket = headers.get("upgrade", "").lower() == "websocket"

        content_length = int(headers.get("content-length", "0"))
        body = leftover
        while len(body) < content_length:
            chunk = await asyncio.wait_for(client_reader.read(content_length - len(body)), timeout=30)
            if not chunk:
                break
            body += chunk

        upstream_reader, upstream_writer = await asyncio.open_connection(upstream_host, upstream_port)

        forwarded = _rebuild_request(method, path, headers, body, upstream_host, upstream_port)
        upstream_writer.write(forwarded)
        await upstream_writer.drain()

        if is_websocket:
            resp_header = b""
            while b"\r\n\r\n" not in resp_header:
                chunk = await asyncio.wait_for(upstream_reader.read(BUF_SIZE), timeout=30)
                if not chunk:
                    client_writer.close()
                    upstream_writer.close()
                    return
                resp_header += chunk

            client_writer.write(resp_header)
            await client_writer.drain()

            t1 = asyncio.create_task(_pipe(client_reader, upstream_writer))
            t2 = asyncio.create_task(_pipe(upstream_reader, client_writer))
            await asyncio.gather(t1, t2, return_exceptions=True)
        else:
            resp = b""
            while True:
                chunk = await asyncio.wait_for(upstream_reader.read(BUF_SIZE), timeout=120)
                if not chunk:
                    break
                resp += chunk
                if b"content-length:" in resp.lower()[:2048]:
                    hdr_end = resp.find(b"\r\n\r\n")
                    if hdr_end >= 0:
                        hdr_text = resp[:hdr_end].decode("latin-1", errors="replace").lower()
                        for line in hdr_text.split("\r\n"):
                            if line.startswith("content-length:"):
                                expected = int(line.split(":", 1)[1].strip())
                                body_so_far = len(resp) - hdr_end - 4
                                if body_so_far >= expected:
                                    break
                        else:
                            continue
                        break
                if len(resp) > 10 * 1024 * 1024:
                    break

            client_writer.write(resp)
            await client_writer.drain()
            client_writer.close()
            upstream_writer.close()

    except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError, OSError) as e:
        log.debug("connection error: %s", e)
    except Exception:
        log.exception("unexpected error in handler")
    finally:
        try:
            client_writer.close()
        except Exception:
            pass


async def run_server(listen_port: int, upstream_host: str, upstream_port: int):
    async def on_connect(reader, writer):
        await handle_client(reader, writer, upstream_host, upstream_port)

    server = await asyncio.start_server(on_connect, "0.0.0.0", listen_port)
    log.info("listening on 0.0.0.0:%d -> %s:%d", listen_port, upstream_host, upstream_port)
    async with server:
        await server.serve_forever()


def main():
    listen_port = int(os.environ.get("AUTH_PROXY_LISTEN_PORT", "8080"))
    upstream_host = os.environ.get("AUTH_PROXY_UPSTREAM_HOST", "127.0.0.1")
    upstream_port = int(os.environ.get("AUTH_PROXY_UPSTREAM_PORT", "9119"))
    asyncio.run(run_server(listen_port, upstream_host, upstream_port))
    return 0


if __name__ == "__main__":
    sys.exit(main())
