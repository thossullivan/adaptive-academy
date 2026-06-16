from urllib.parse import parse_qsl, urlencode, urlsplit

from adaptive_academy.llm.researcher_types import RawSource, SearchBrief

# (angle_key, query_template) — {topic} is filled in. Order is the fan-out order.
ANGLES: list[tuple[str, str]] = [
    ("foundational_papers", "Seminal / foundational papers for learning {topic}"),
    ("canonical_tutorials", "Best canonical tutorials, courses, or lectures for {topic}"),
    ("key_concepts", "Key concepts and prerequisites someone must understand for {topic}"),
    ("reference_implementations", "Well-regarded reference implementations or codebases for {topic}"),
    ("critiques", "Critiques, limitations, and common misconceptions about {topic}"),
]


def build_briefs(topic: str, intent: str, n: int) -> list[SearchBrief]:
    """Deterministic fan-out angles. Caps at the number of defined ANGLES."""
    count = max(0, min(n, len(ANGLES)))
    briefs: list[SearchBrief] = []
    for angle, template in ANGLES[:count]:
        query = template.format(topic=topic)
        if intent:
            query = f"{query}. Learner goal: {intent}"
        briefs.append(SearchBrief(angle=angle, query=query))
    return briefs


_TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "ref_src", "mc_cid", "mc_eid",
}


def canonicalize_url(url: str) -> str:
    """Normalize a URL for dedup: drop scheme/www/trailing-slash/fragment/tracking params."""
    raw = url.strip()
    parts = urlsplit(raw if "//" in raw else "//" + raw)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    kept = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING]
    query = urlencode(sorted(kept))
    canon = host + path
    if query:
        canon += "?" + query
    return canon


def _richness(s: RawSource) -> tuple:
    """Higher is richer: prefer a summary, then a why, then relevance, then tier."""
    return (bool(s.summary), bool(s.why), s.relevance, -s.tier)


def dedupe_by_url(sources: list[RawSource]) -> list[RawSource]:
    """Collapse duplicate URLs, keeping the richest record. Deterministic order (by canonical url)."""
    best: dict[str, RawSource] = {}
    for s in sources:
        key = canonicalize_url(s.url)
        if key not in best or _richness(s) > _richness(best[key]):
            best[key] = s
    return [best[k] for k in sorted(best)]
