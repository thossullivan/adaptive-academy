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
