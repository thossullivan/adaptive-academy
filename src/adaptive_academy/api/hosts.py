"""Which Host headers the API answers (a guard against DNS rebinding).

The app has no login: it is meant to be reached on this machine only. A web page on another
site can still point a name it controls at 127.0.0.1 and make the browser send requests here
under that name ("DNS rebinding"); the Host header then carries that name. So the API answers
only the local names below, plus any listed in AA_ALLOWED_HOSTS, and says 400 to the rest.

Starlette's TrustedHostMiddleware cuts the port off with split(":"), which also cuts an IPv6
literal ("[::1]:8000" becomes "["); this subclass reads the host part properly.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

# This machine by name and address. 0.0.0.0 is an address, so no DNS name can be rebound to
# it. (The test suite adds TestClient's "testserver" through AA_ALLOWED_HOSTS.)
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]", "0.0.0.0")


def allowed_hosts(extra: str = "") -> list[str]:
    """The local names plus the comma-separated `extra` (AA_ALLOWED_HOSTS), lower-cased."""
    names = [h.strip().lower() for h in (extra or "").split(",") if h.strip()]
    return list(dict.fromkeys([*LOCAL_HOSTS, *names]))


def host_name(header: str) -> str:
    """The host part of a Host header, without the port: "[::1]:8000" -> "[::1]"."""
    header = header.strip().lower()
    if header.startswith("["):
        end = header.find("]")
        return header[: end + 1] if end != -1 else header
    return header.split(":", 1)[0]


class LocalHostMiddleware(TrustedHostMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.allow_any or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        host = host_name(Headers(scope=scope).get("host", ""))
        for pattern in self.allowed_hosts:
            if host == pattern or (pattern.startswith("*.") and host.endswith(pattern[1:])):
                await self.app(scope, receive, send)
                return
        response = PlainTextResponse(
            "This host name is not allowed. Open the app at localhost, or add the name to "
            "AA_ALLOWED_HOSTS.", status_code=400)
        await response(scope, receive, send)
