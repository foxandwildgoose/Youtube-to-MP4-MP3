"""Pinned-address HTTPS fetch for thumbnails only."""

from __future__ import annotations

import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin

from app.errors import AppError

THUMB_HOSTS = {"i.ytimg.com", "i9.ytimg.com", "yt3.ggpht.com", "img.youtube.com"}
BLOCKED = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
]


def ip_blocked(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return True
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    ):
        return True
    return any(addr in network for network in BLOCKED)


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise AppError("SOURCE_UNAVAILABLE", 502) from exc
    ips = []
    for info in infos:
        ip = info[4][0]
        if ip_blocked(ip):
            raise AppError("BAD_REQUEST", 400)
        ips.append(ip)
    if not ips:
        raise AppError("BAD_REQUEST", 400)
    return ips


def fetch_thumbnail(url: str, timeout: float = 8, max_bytes: int = 2_000_000) -> tuple[bytes, str]:
    current = url
    for _ in range(3):
        parts = urlsplit(current)
        if parts.scheme != "https" or parts.username or parts.password:
            raise AppError("BAD_REQUEST", 400)
        host = (parts.hostname or "").lower()
        if host not in THUMB_HOSTS:
            raise AppError("BAD_REQUEST", 400)
        port = parts.port or 443
        ips = _resolve(host, port)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        data, status, headers = _read(ips[0], port, host, path, timeout, max_bytes)
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location:
                raise AppError("SOURCE_UNAVAILABLE", 502)
            current = urljoin(current, location)
            continue
        if status != 200:
            raise AppError("SOURCE_UNAVAILABLE", 502)
        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype not in {"image/jpeg", "image/png", "image/webp"}:
            raise AppError("OUTPUT_INVALID", 415)
        if not data or len(data) > max_bytes:
            raise AppError("LIMIT_EXCEEDED", 413)
        return data, ctype
    raise AppError("SOURCE_UNAVAILABLE", 502)


def _read(ip: str, port: int, host: str, path: str, timeout: float, max_bytes: int) -> tuple[bytes, int, dict[str, str]]:
    sock = socket.create_connection((ip, port), timeout=timeout)
    try:
        context = ssl.create_default_context()
        tls = context.wrap_socket(sock, server_hostname=host)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "User-Agent: seorap-thumbnail/1.0\r\n"
            "Accept: image/jpeg,image/png,image/webp\r\n"
            "Connection: close\r\n\r\n"
        )
        tls.sendall(request.encode("ascii"))
        chunks = bytearray()
        while len(chunks) < max_bytes + 8192:
            piece = tls.recv(65536)
            if not piece:
                break
            chunks.extend(piece)
        tls.close()
    finally:
        sock.close()
    raw = bytes(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
    status = int(lines[0].split(" ", 2)[1])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    if "content-length" in headers and int(headers["content-length"]) > max_bytes:
        raise AppError("LIMIT_EXCEEDED", 413)
    return body[: max_bytes + 1], status, headers
