"""Separate HTTP bearer credentials, bounded body and per-key resource limits."""
import asyncio
import json
import time
from collections import deque

from .keys import verify_key

MAX_BODY = 8 * 1024 * 1024
MAX_CONCURRENT = 4
REQUESTS_PER_MINUTE = 120
BODY_TIMEOUT = 30


async def _error(send, status, code):
    body = json.dumps({"error": code}).encode()
    headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
               (b"content-length", str(len(body)).encode())]
    if status == 401:
        headers.append((b"www-authenticate", b'Bearer realm="CLMS MCP"'))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class MCPRequestGuard:
    def __init__(self, app, vault, maximum=MAX_BODY):
        self.app, self.vault, self.maximum = app, vault, maximum
        self.recent, self.active = {}, {}

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        if scope.get("path") not in {"/mcp", "/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"} or scope.get("query_string"):
            return await _error(send, 404, "not_found")
        if scope.get("path") != "/mcp":
            return await self.app(scope, receive, send)
        headers = list(scope.get("headers") or [])
        auth = [v for k, v in headers if k.lower() == b"authorization"]
        alternate = [v for k, v in headers if k.lower() == b"x-clms-mcp-key"]
        if len(auth) > 1 or len(alternate) > 1 or (auth and alternate):
            return await _error(send, 401, "invalid_credentials")
        token = None
        if auth and auth[0].lower().startswith(b"bearer "):
            token = auth[0][7:]
        elif not auth and alternate:
            token = alternate[0]; headers.append((b"authorization", b"Bearer " + token))
        if not token or len(token) > 512:
            return await _error(send, 401, "invalid_credentials")
        try:
            identity = await asyncio.to_thread(verify_key, self.vault, token.decode("ascii"))
        except (UnicodeError, OSError, ValueError):
            identity = None
        if not identity:
            return await _error(send, 401, "invalid_credentials")
        key_id, now = identity["key_id"], time.monotonic()
        for stale in list(self.recent):
            while self.recent[stale] and self.recent[stale][0] <= now - 60:
                self.recent[stale].popleft()
            if not self.recent[stale] and not self.active.get(stale):
                self.recent.pop(stale, None); self.active.pop(stale, None)
        queue = self.recent.setdefault(key_id, deque())
        if len(queue) >= REQUESTS_PER_MINUTE or self.active.get(key_id, 0) >= MAX_CONCURRENT:
            return await _error(send, 429, "rate_limited")
        queue.append(now); self.active[key_id] = self.active.get(key_id, 0) + 1
        try:
            lengths = [value for key, value in headers if key.lower() == b"content-length"]
            if lengths:
                try:
                    length = int(lengths[0])
                except ValueError:
                    length = -1
                if len(lengths) != 1 or length < 0:
                    return await _error(send, 400, "invalid_length")
                if length > self.maximum:
                    return await _error(send, 413, "too_large")
            messages, total, deadline = [], 0, now + BODY_TIMEOUT
            while True:
                try:
                    message = await asyncio.wait_for(receive(), timeout=max(.001, deadline - time.monotonic()))
                except TimeoutError:
                    return await _error(send, 408, "body_timeout")
                if message["type"] == "http.disconnect":
                    return
                total += len(message.get("body", b""))
                if total > self.maximum:
                    return await _error(send, 413, "too_large")
                messages.append(message)
                if not message.get("more_body", False):
                    break
            position = 0

            async def replay():
                nonlocal position
                if position < len(messages):
                    message = messages[position]; position += 1; return message
                return await receive()

            forwarded = dict(scope); forwarded["headers"] = headers
            return await self.app(forwarded, replay, send)
        finally:
            self.active[key_id] -= 1
