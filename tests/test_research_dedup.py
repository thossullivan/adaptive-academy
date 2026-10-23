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


def test_strip_cite_tags_keeps_the_inner_text():
    from adaptive_academy.engine.research import strip_cite_tags

    leaked = "<cite index='20-11,20-12'>The paper starts from</cite> optional stopping."
    assert strip_cite_tags(leaked) == "The paper starts from optional stopping."
    assert strip_cite_tags('<cite index="3-1">Quoted</cite>') == "Quoted"
    nested = "<cite index='1-1'>a <CITE index='2-2'>b</cite> c</cite> and <cite index='4'>d</cite>"
    assert strip_cite_tags(nested) == "a b c and d"
    assert strip_cite_tags("x < y and <citation> stays") == "x < y and <citation> stays"


def test_dedupe_by_title_collapses_the_same_paper_under_two_urls():
    from adaptive_academy.engine.research import dedupe_by_title

    title = "Continuous Monitoring of A/B Tests without Pain: Optional Stopping in Bayesian Testing"
    src = [
        RawSource(title=f"{title} (Deng, Liu, Chen)", url="https://a.org/paper", tier=2),
        RawSource(title="Other work", url="https://b.org", tier=1),
        RawSource(title=f"{title.upper()}! (Deng, Lu, Chen, 2016)", url="https://c.org/x", tier=1),
        RawSource(title=f"{title} (again)", url="https://d.org", tier=2),
    ]
    out = dedupe_by_title(src)
    # The tier-1 copy replaces the tier-2 one in its slot; the later tier-2 copy is dropped.
    assert [s.url for s in out] == ["https://c.org/x", "https://b.org"]


def test_dedupe_by_title_keeps_first_on_equal_tier_and_ignores_generic_titles():
    from adaptive_academy.engine.research import dedupe_by_title

    src = [
        RawSource(title="Bayesian A/B Testing Explained", url="https://a.org", tier=2),
        RawSource(title="bayesian a-b testing, explained", url="https://b.org", tier=2),
        RawSource(title="Introduction", url="https://c.org", tier=3),
        RawSource(title="Introduction", url="https://d.org", tier=3),
    ]
    assert [s.url for s in dedupe_by_title(src)] == [
        "https://a.org", "https://c.org", "https://d.org"]
