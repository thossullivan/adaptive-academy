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
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

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


def _http_get(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "adaptive-academy/artifact-fetch"})
    with urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310  scheme/host validated by caller
        return resp.read(MAX_BYTES + 1)


def fetch_artifact_text(
    url: str,
    *,
    resolve: Callable[[str], list[str]] = _resolve_host,
    get: Callable[[str], bytes] = _http_get,
) -> str | None:
    """Return the URL's text (size-capped, stripped) or None if it can't be fetched safely."""
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https":
        return None
    host = parts.hostname or ""
    if not _host_allowed(host):
        return None
    try:
        addrs = resolve(host)
    except OSError:
        return None
    if not addrs or not all(_ip_is_public(a) for a in addrs):
        return None
    try:
        raw = get(url)
    except Exception:
        return None
    if not raw:
        return None
    text = raw[:MAX_BYTES].decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    text = text.strip()
    return text or None
