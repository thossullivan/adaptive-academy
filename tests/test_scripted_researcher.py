
from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient


def test_scripted_returns_canned_sources_by_angle():
    client = ScriptedResearcherClient(
        {
            "foundational_papers": [
                RawSource(title="Attention", url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.95)
            ],
            "critiques": [],
        }
    )
    brief = SearchBrief(angle="foundational_papers", query="transformer foundational papers")
    out = client.search(brief)
    assert len(out) == 1
    assert out[0].title == "Attention"
    assert client.calls == ["foundational_papers"]


def test_scripted_unknown_angle_returns_empty():
    client = ScriptedResearcherClient({})
    assert client.search(SearchBrief(angle="whatever", query="q")) == []
