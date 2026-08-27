"""SSRF-guarded best-effort fetch of artifact URLs. All tests are hermetic: the DNS
resolver and the HTTP getter are injected, so nothing here touches the network."""

from adaptive_academy.engine.fetch import MAX_BYTES, fetch_artifact_text

PUBLIC = lambda _host: ["140.82.112.3"]  # noqa: E731  pretend the host is public
BODY = lambda _url: b"# README\nhello world"  # noqa: E731


def test_rejects_non_https_scheme():
    assert fetch_artifact_text("http://github.com/me/proj", resolve=PUBLIC, get=BODY) is None
    assert fetch_artifact_text("file:///etc/passwd", resolve=PUBLIC, get=BODY) is None


def test_rejects_non_allowlisted_host():
    assert fetch_artifact_text("https://evil.example.com/x", resolve=PUBLIC, get=BODY) is None
    # a look-alike that only *contains* an allowed token is still rejected
    assert fetch_artifact_text("https://github.com.evil.com/x", resolve=PUBLIC, get=BODY) is None


def test_rejects_when_allowlisted_host_resolves_to_private_ip():
    # DNS-rebind defense: even an allowlisted host is blocked if it resolves internally.
    private = lambda _host: ["127.0.0.1"]  # noqa: E731
    assert fetch_artifact_text(
        "https://raw.githubusercontent.com/me/p/main/README.md", resolve=private, get=BODY) is None
    link_local = lambda _host: ["169.254.169.254"]  # noqa: E731  cloud metadata endpoint
    assert fetch_artifact_text(
        "https://raw.githubusercontent.com/x", resolve=link_local, get=BODY) is None


def test_returns_fetched_text_on_success():
    got = fetch_artifact_text(
        "https://raw.githubusercontent.com/me/proj/main/README.md", resolve=PUBLIC, get=BODY)
    assert got == "# README\nhello world"


def test_truncates_to_size_cap():
    big = lambda _url: b"x" * (MAX_BYTES + 5000)  # noqa: E731
    got = fetch_artifact_text("https://raw.githubusercontent.com/a", resolve=PUBLIC, get=big)
    assert len(got) == MAX_BYTES


def test_returns_none_on_fetch_error():
    def boom(_url):
        raise OSError("network down")

    assert fetch_artifact_text(
        "https://raw.githubusercontent.com/a", resolve=PUBLIC, get=boom) is None


def test_returns_none_on_empty_body():
    assert fetch_artifact_text(
        "https://raw.githubusercontent.com/a", resolve=PUBLIC, get=lambda _u: b"   ") is None


def _public(_host):
    return ["93.184.216.34"]


def test_redirect_to_non_https_or_internal_target_is_refused():
    def respond(url):
        if url == "https://github.com/x":
            return 302, "http://169.254.169.254/latest/meta-data/", b""
        raise AssertionError(f"unexpected request {url}")

    assert fetch_artifact_text("https://github.com/x", resolve=_public, get_response=respond) is None


def test_redirect_to_allowlisted_https_target_is_followed_once_validated():
    seen = []

    def respond(url):
        seen.append(url)
        if url == "https://github.com/x":
            return 301, "https://raw.githubusercontent.com/x/README.md", b""
        return 200, None, b"followed body"

    assert (
        fetch_artifact_text("https://github.com/x", resolve=_public, get_response=respond)
        == "followed body"
    )
    assert seen == ["https://github.com/x", "https://raw.githubusercontent.com/x/README.md"]


def test_redirect_to_non_allowlisted_https_host_is_refused():
    def respond(url):
        return 302, "https://evil.example.org/", b""

    assert fetch_artifact_text("https://github.com/x", resolve=_public, get_response=respond) is None


def test_redirect_chain_is_bounded():
    def respond(url):
        return 302, "https://github.com/next", b""

    assert fetch_artifact_text("https://github.com/x", resolve=_public, get_response=respond) is None


def test_default_opener_does_not_follow_redirects():
    from urllib.request import HTTPRedirectHandler

    from adaptive_academy.engine import fetch as fetch_mod

    handler = next(h for h in fetch_mod._OPENER.handlers if isinstance(h, HTTPRedirectHandler))
    assert type(handler).__name__ == "_NoRedirect"
    assert handler.redirect_request(None, None, 302, "Found", {}, "https://x/") is None
