from adaptive_academy.engine.research import rank_sources, score_source
from adaptive_academy.llm.researcher_types import RawSource


def test_score_weights_tier_and_relevance():
    hi = RawSource(title="A", url="a", tier=1, relevance=0.9)
    lo = RawSource(title="B", url="b", tier=3, relevance=0.4)
    assert score_source(hi) > score_source(lo)


def test_rank_orders_by_score_desc_with_stable_url_tiebreak():
    src = [
        RawSource(title="t3", url="https://c.com", tier=2, relevance=0.5),
        RawSource(title="t1", url="https://a.com", tier=1, relevance=0.9),
        RawSource(title="t2", url="https://b.com", tier=1, relevance=0.9),  # ties with a.com on score
    ]
    out = rank_sources(src)
    assert [s.url for s in out] == ["https://a.com", "https://b.com", "https://c.com"]
    # tie between a.com and b.com broken by url ascending


def test_rank_is_pure_does_not_mutate_input():
    src = [RawSource(title="x", url="x", tier=3, relevance=0.1)]
    before = list(src)
    rank_sources(src)
    assert src == before
