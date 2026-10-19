"""Bound actual ASGI request bytes before any JSON/body buffering layer."""

import asyncio

from starlette.responses import JSONResponse

from app.errors import AppError, envelope


class RequestBodyLimit:
    def __init__(self, app, max_bytes: int = 65536, timeout: float = 15):
        self.app = app
        self.max_bytes = max_bytes
        self.timeout = timeout

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/api'):
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        locale = 'en' if headers.get(b'x-locale') == b'en' else 'ko'

        async def reject(status, code):
            response = JSONResponse(envelope(AppError(code, status), locale), status_code=status)
            await response(scope, receive, send)

        length = headers.get(b'content-length')
        if length is not None:
            try:
                declared = int(length)
                if declared < 0:
                    raise ValueError
            except ValueError:
                return await reject(400, 'BAD_REQUEST')
            if declared > self.max_bytes:
                return await reject(413, 'LIMIT_EXCEEDED')
        chunks = bytearray()
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    chunks.extend(message.get('body', b''))
                    if len(chunks) > self.max_bytes:
                        return await reject(413, 'LIMIT_EXCEEDED')
                    if not message.get('more_body', False):
                        break
        except TimeoutError:
            return await reject(408, 'BAD_REQUEST')
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(chunks), 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)
