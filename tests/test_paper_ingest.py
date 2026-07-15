import pytest

from adaptive_academy.engine.paper import MAX_CHARS, PaperExtract, PaperIngestError, ingest_paper


def test_paste_passthrough():
    out = ingest_paper(pasted_text="  We study X.  ", title="My Paper")
    assert out == PaperExtract(title="My Paper", text="We study X.", source="paste")


def test_paste_title_falls_back_to_first_line():
    out = ingest_paper(pasted_text="A Great Result\nbody line")
    assert out.title == "A Great Result" and out.source == "paste"


def test_paste_is_char_capped():
    out = ingest_paper(pasted_text="x" * (MAX_CHARS + 500))
    assert len(out.text) == MAX_CHARS


def test_arxiv_abs_url_normalized_and_stripped():
    seen = {}

    def fake_fetch(url, *, max_bytes):
        seen["url"] = url
        seen["max_bytes"] = max_bytes
        return "<html><head><title>tt</title></head><body><h1>Attention</h1>" \
               "<script>ignore()</script><p>We propose the Transformer.</p></body></html>"

    out = ingest_paper(url="https://arxiv.org/abs/1706.03762v5", fetch=fake_fetch)
    assert seen["url"] == "https://arxiv.org/html/1706.03762"
    assert seen["max_bytes"] == 2_000_000
    assert out.source == "arxiv"
    assert out.title == "Attention"
    assert "We propose the Transformer." in out.text
    assert "ignore()" not in out.text


def test_non_arxiv_url_without_paste_raises():
    with pytest.raises(PaperIngestError):
        ingest_paper(url="https://example.com/paper.pdf")


def test_empty_raises():
    with pytest.raises(PaperIngestError):
        ingest_paper()


def test_arxiv_fetch_returns_none_raises():
    with pytest.raises(PaperIngestError):
        ingest_paper(url="https://arxiv.org/abs/1706.03762", fetch=lambda url, *, max_bytes: None)
