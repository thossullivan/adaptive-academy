"""Best-effort, SSRF-guarded fetch of an artifact URL's text.

The learner ships a deliverable with a URL (repo README, blog post, notebook). This pulls the
text so the grader sees the actual work, not just pasted notes. Fetching arbitrary user-supplied
URLs server-side is an SSRF surface, so this is deliberately conservative:

  * https only;
  * host must be on a small allowlist of known-public artifact/content hosts;
  * the host must resolve to a *public* address (DNS-rebind / metadata-endpoint defense);
  * the body is size-capped and the request is short-timeout;
  * any failure degrades silently to None — the caller falls back to paste-only.

`resolve` and `get` are injectable so the guard logic is testable without touching the network.
"""

import ipaddress
import socket
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

# Known-public hosts that serve raw artifact/writeup text. Suffix-matched against the hostname,
# so "raw.githubusercontent.com" matches the "githubusercontent.com" entry. Keep this tight.
ALLOWED_HOST_SUFFIXES: tuple[str, ...] = (
    "github.com",
    "githubusercontent.com",
    "github.io",
    "gitlab.com",
    "gitlab.io",
    "bitbucket.org",
    "arxiv.org",
    "huggingface.co",
    "kaggle.com",
    "medium.com",
    "substack.com",
    "dev.to",
    "readthedocs.io",
)
MAX_BYTES = 200_000
TIMEOUT_S = 6.0
MAX_REDIRECTS = 3
_REDIRECT_CODES = {301, 302, 303, 307, 308}


def _host_allowed(host: str) -> bool:
    host = host.strip().lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def _ip_is_public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
        or ip.is_multicast or ip.is_unspecified
    )


def _resolve_host(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


class _NoRedirect(HTTPRedirectHandler):
    """Never follow a redirect automatically: every hop is re-validated by the caller."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = build_opener(_NoRedirect())


def _http_get_response(url: str, max_bytes: int = MAX_BYTES) -> tuple[int, str | None, bytes]:
    """One request, no redirect following. Returns (status, Location-or-None, body)."""
    req = Request(url, headers={"User-Agent": "adaptive-academy/artifact-fetch"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as resp:  # noqa: S310  validated by caller
            return resp.status, None, resp.read(max_bytes + 1)
    except HTTPError as err:
        if err.code in _REDIRECT_CODES:
            return err.code, err.headers.get("Location"), b""
        raise


def _http_get(url: str, max_bytes: int = MAX_BYTES) -> bytes:
    _status, _location, body = _http_get_response(url, max_bytes)
    return body


def _url_is_safe(url: str, resolve: Callable[[str], list[str]]) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https":
        return False
    host = parts.hostname or ""
    if not _host_allowed(host):
        return False
    try:
        addrs = resolve(host)
    except OSError:
        return False
    return bool(addrs) and all(_ip_is_public(a) for a in addrs)


def fetch_artifact_text(
    url: str,
    *,
    resolve: Callable[[str], list[str]] = _resolve_host,
    get: Callable[[str], bytes] | None = None,
    get_response: Callable[[str], tuple[int, str | None, bytes]] | None = None,
    max_bytes: int = MAX_BYTES,
) -> str | None:
    """Return the URL's text (size-capped, stripped) or None if it can't be fetched safely.

    Redirects are never followed automatically: each hop (at most MAX_REDIRECTS) must pass
    the same https / allowlist / public-address checks as the first URL, so an allowlisted
    host cannot bounce the fetch to a metadata endpoint or an internal address.
    """
    if not url or not _url_is_safe(url, resolve):
        return None
    if get is not None:
        # Legacy single-request getter (tests): no redirect chain possible.
        try:
            raw = get(url)
        except Exception:
            return None
    else:
        respond = get_response or (lambda u: _http_get_response(u, max_bytes))
        raw = b""
        current = url
        try:
            for _hop in range(MAX_REDIRECTS + 1):
                status, location, body = respond(current)
                if status in _REDIRECT_CODES:
                    if not location:
                        return None
                    current = urljoin(current, location)
                    if not _url_is_safe(current, resolve):
                        return None
                    continue
                raw = body
                break
            else:
                return None  # too many hops
        except Exception:
            return None
    if not raw:
        return None
    text = raw[:max_bytes].decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    text = text.strip()
    return text or None
