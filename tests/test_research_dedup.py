from adaptive_academy.engine.research import canonicalize_url, dedupe_by_url
from adaptive_academy.llm.researcher_types import RawSource


def test_canonicalize_strips_scheme_www_slash_and_tracking():
    a = canonicalize_url("https://www.Example.com/path/?utm_source=x&id=7#frag")
    b = canonicalize_url("http://example.com/path?id=7")
    assert a == b == "example.com/path?id=7"


def test_canonicalize_keeps_meaningful_query_sorted():
    assert canonicalize_url("https://youtube.com/watch?v=abc&t=10") == "youtube.com/watch?t=10&v=abc"


def test_dedupe_merges_duplicates_keeping_richer_record():
    src = [
        RawSource(title="Attention", url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.9, summary=""),
        RawSource(title="Attention (dup)", url="http://www.arxiv.org/abs/1706.03762/", tier=1, relevance=0.8, summary="A summary"),
        RawSource(title="Other", url="https://example.com/x", tier=2, relevance=0.5),
    ]
    out = dedupe_by_url(src)
    assert len(out) == 2
    kept = next(s for s in out if "arxiv" in s.url)
    assert kept.summary == "A summary"  # richer record won


def test_dedupe_is_deterministic_in_order():
    src = [
        RawSource(title="B", url="https://b.com", tier=2, relevance=0.5),
        RawSource(title="A", url="https://a.com", tier=1, relevance=0.9),
    ]
    assert [s.url for s in dedupe_by_url(src)] == ["https://a.com", "https://b.com"]
