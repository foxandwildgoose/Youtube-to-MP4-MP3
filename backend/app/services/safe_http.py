"""Pinned-address HTTPS fetch for thumbnails only."""

from __future__ import annotations

import ipaddress
import http.client
import time
import threading
import io
import warnings
from concurrent.futures import ThreadPoolExecutor, TimeoutError as ResolveTimeout
from collections import OrderedDict
import socket
import ssl
from urllib.parse import urlsplit, urljoin

from app.errors import AppError
from PIL import Image

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
_DNS_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='thumbnail-dns')
_DNS_CAPACITY = threading.BoundedSemaphore(2)


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


def _resolve_with_deadline(host: str, port: int, timeout: float) -> list[str]:
    # getaddrinfo itself has no Python timeout. Bound caller time and concurrent
    # resolver work without accumulating an unbounded executor queue.
    if timeout <= 0 or not _DNS_CAPACITY.acquire(blocking=False):
        raise AppError('SOURCE_UNAVAILABLE', 504)
    try:
        pending = _DNS_POOL.submit(_resolve, host, port)
    except BaseException:
        _DNS_CAPACITY.release()
        raise
    pending.add_done_callback(lambda _future: _DNS_CAPACITY.release())
    try:
        return pending.result(timeout=timeout)
    except ResolveTimeout as exc:
        raise AppError('SOURCE_UNAVAILABLE', 504) from exc


# Bounded process-local cache. Failures are never cached.
_CACHE: OrderedDict[str, tuple[float, bytes, str]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_BYTES = 16_000_000


def _image_valid(data: bytes, ctype: str) -> bool:
    allowed = {'image/jpeg': 'JPEG', 'image/png': 'PNG', 'image/webp': 'WEBP'}
    if ctype not in allowed:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != allowed[ctype] or image.width * image.height > 16_000_000:
                    return False
                image.verify()
            # Decode as well: structural verify alone does not detect JPEG truncation.
            with Image.open(io.BytesIO(data)) as image:
                image.load()
        return True
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return False


def fetch_thumbnail(url: str, timeout: float = 8, max_bytes: int = 2_000_000) -> tuple[bytes, str]:
    with _CACHE_LOCK:
        hit = _CACHE.get(url)
        if hit and hit[0] > time.monotonic() and len(hit[1]) <= max_bytes:
            _CACHE.move_to_end(url)
            return hit[1], hit[2]
    deadline = time.monotonic() + timeout
    current = url
    for _ in range(3):
        try:
            parts = urlsplit(current)
            port = parts.port or 443
            host = (parts.hostname or "").lower()
        except ValueError as exc:
            raise AppError("BAD_REQUEST", 400) from exc
        if parts.scheme != "https" or parts.username or parts.password or port != 443 or host not in THUMB_HOSTS:
            raise AppError("BAD_REQUEST", 400)
        if any(ord(ch) < 33 or ord(ch) > 126 for ch in current):
            raise AppError("BAD_REQUEST", 400)
        ips = _resolve_with_deadline(host, port, deadline - time.monotonic())
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AppError("SOURCE_UNAVAILABLE", 504)
        data, status, headers = _read(ips[0], port, host, path, remaining, max_bytes)
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location:
                raise AppError("SOURCE_UNAVAILABLE", 502)
            current = urljoin(current, location)
            continue
        if status != 200:
            raise AppError("SOURCE_UNAVAILABLE", 502)
        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        if not _image_valid(data, ctype):
            raise AppError("OUTPUT_INVALID", 415)
        if not data or len(data) > max_bytes:
            raise AppError("LIMIT_EXCEEDED", 413)
        with _CACHE_LOCK:
            _CACHE[url] = (time.monotonic() + 300, data, ctype)
            while len(_CACHE) > 32 or sum(len(item[1]) for item in _CACHE.values()) > _CACHE_BYTES:
                _CACHE.popitem(last=False)
        return data, ctype
    raise AppError("SOURCE_UNAVAILABLE", 502)


class _BudgetReader:
    """HTTPResponse handles framing; this bounds raw/header bytes and wall time."""
    def __init__(self, reader, tls, deadline, max_bytes):
        self.reader = reader
        self.tls = tls
        self.deadline = deadline
        self.remaining = max_bytes * 2 + 32768
        self.header_remaining = 16384
        self.headers = True

    def _before(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        self.tls.settimeout(remaining)

    def _count(self, data):
        self.remaining -= len(data)
        if self.remaining < 0:
            raise AppError("LIMIT_EXCEEDED", 413)
        if time.monotonic() > self.deadline:
            raise TimeoutError
        return data

    def readline(self, size=-1):
        self._before()
        data = self._count(self.reader.readline(min(size if size >= 0 else 16385, 16385)))
        if self.headers:
            self.header_remaining -= len(data)
            if self.header_remaining < 0:
                raise AppError("LIMIT_EXCEEDED", 413)
            if data in (b"\r\n", b"\n"):
                self.headers = False
        return data

    def read(self, size=-1):
        self._before()
        return self._count(self.reader.read(size))

    def close(self):
        self.reader.close()

    def flush(self):
        # HTTPResponse inherits IOBase and may flush before closing early.
        pass


class _ResponseSocket:
    def __init__(self, tls, deadline, max_bytes):
        self.tls, self.deadline, self.max_bytes = tls, deadline, max_bytes

    def makefile(self, mode):
        return _BudgetReader(self.tls.makefile(mode), self.tls, self.deadline, self.max_bytes)


def _read(ip: str, port: int, host: str, path: str, timeout: float, max_bytes: int) -> tuple[bytes, int, dict[str, str]]:
    deadline = time.monotonic() + timeout
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            with ssl.create_default_context().wrap_socket(sock, server_hostname=host) as tls:
                request = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                           "User-Agent: seorap-thumbnail/1.0\r\nAccept: image/jpeg,image/png,image/webp\r\n"
                           "Connection: close\r\n\r\n")
                tls.sendall(request.encode("ascii"))
                response = http.client.HTTPResponse(_ResponseSocket(tls, deadline, max_bytes))
                try:
                    response.begin()
                    headers = {key.lower(): value for key, value in response.getheaders()}
                    length = headers.get("content-length")
                    if length is not None and (int(length) < 0 or int(length) > max_bytes):
                        raise AppError("LIMIT_EXCEEDED", 413)
                    body = bytearray()
                    while True:
                        piece = response.read(min(65536, max_bytes + 1 - len(body)))
                        if not piece:
                            break
                        body.extend(piece)
                        if len(body) > max_bytes:
                            raise AppError("LIMIT_EXCEEDED", 413)
                    if response.length not in (None, 0):
                        raise AppError("SOURCE_UNAVAILABLE", 502)
                    return bytes(body), response.status, headers
                finally:
                    response.close()
    except AppError:
        raise
    except (OSError, ValueError, UnicodeError, http.client.HTTPException) as exc:
        raise AppError("SOURCE_UNAVAILABLE", 502) from exc
