"""Ingest a paper into probe-ready text.

Two paths: (1) an arXiv URL is normalized to the full-text HTML endpoint and fetched through
the existing SSRF-guarded `fetch_artifact_text` (with a larger byte cap for a deliberate
single-document pull), then stripped to text with a stdlib HTML parser; (2) pasted text is
used directly. Everything else asks the caller to paste. No new dependency, no PDF parsing.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

from adaptive_academy.engine.fetch import fetch_artifact_text

PAPER_MAX_BYTES = 2_000_000
MAX_CHARS = 60_000
_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


@dataclass
class PaperExtract:
    title: str
    text: str
    source: str


class PaperIngestError(ValueError):
    """The paper could not be ingested; the caller should surface a paste-instead message."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._parts: list[str] = []
        self._title = ""
        self._in_title = False
        self._h1 = ""
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "h1" and not self._h1:
            self._in_h1 = True

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, data):
        if self._skip:
            return
        stripped = data.strip()
        if self._in_title and not self._title:
            self._title = stripped
        if self._in_h1 and not self._h1:
            self._h1 = stripped
        if stripped:
            self._parts.append(stripped)

    def result(self) -> tuple[str, str]:
        return (self._h1 or self._title), "\n".join(self._parts)


def _html_to_text(html: str) -> tuple[str, str]:
    p = _TextExtractor()
    p.feed(html)
    return p.result()


def _arxiv_html_url(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not (host == "arxiv.org" or host.endswith(".arxiv.org")):
        return None
    m = _ARXIV_ID_RE.search(parts.path)
    if not m:
        return None
    return f"https://arxiv.org/html/{m.group(1)}"


def ingest_paper(
    *,
    url: str | None = None,
    pasted_text: str | None = None,
    title: str | None = None,
    fetch: Callable[..., str | None] = fetch_artifact_text,
) -> PaperExtract:
    if pasted_text and pasted_text.strip():
        text = pasted_text.strip()[:MAX_CHARS]
        first_line = text.splitlines()[0][:120] if text else "Untitled paper"
        return PaperExtract(title=(title or "").strip() or first_line, text=text, source="paste")
    if url and url.strip():
        html_url = _arxiv_html_url(url.strip())
        if html_url is None:
            raise PaperIngestError(
                "only arXiv URLs are auto-fetched — paste the paper text instead")
        raw = fetch(html_url, max_bytes=PAPER_MAX_BYTES)
        if not raw:
            raise PaperIngestError(
                "could not fetch the arXiv HTML — paste the paper text instead")
        h1, body = _html_to_text(raw)
        text = body.strip()[:MAX_CHARS]
        if not text:
            raise PaperIngestError(
                "fetched page had no readable text — paste the paper text instead")
        return PaperExtract(title=(title or h1 or "Untitled paper").strip(),
                            text=text, source="arxiv")
    raise PaperIngestError("give an arXiv URL or paste the paper text")
