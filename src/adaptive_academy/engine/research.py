import json
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit

from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
from adaptive_academy.llm.types import LLMClient

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


_TIER_SCORE = {1: 1.0, 2: 0.6, 3: 0.3}
_W_TIER = 0.6
_W_REL = 0.4


def score_source(s: RawSource) -> float:
    """Deterministic relevance/authority score in [0, 1]."""
    tier = _TIER_SCORE.get(s.tier, 0.3)
    rel = max(0.0, min(1.0, s.relevance))
    return _W_TIER * tier + _W_REL * rel


def rank_sources(sources: list[RawSource]) -> list[RawSource]:
    """Return a new list ordered by score desc, tie-broken by url ascending (total order)."""
    return sorted(sources, key=lambda s: (-score_source(s), s.url))


_FOUNDATION_SYSTEM = (
    "You are a research synthesizer for a self-directed advanced adult learner. "
    "Given a topic, the learner's intent, and a ranked reading list, produce a concise "
    "foundation. Respond with ONLY a JSON object with keys: "
    '"overview" (string, 2-4 sentences), "key_concepts" (array of short strings, the '
    'load-bearing ideas), "prerequisite_map" (object mapping each key concept to an array '
    "of prerequisite concept names). No prose outside the JSON."
)


@dataclass
class Foundation:
    overview: str
    key_concepts: list[str]
    prerequisite_map: dict


def _build_foundation_user_msg(topic: str, intent: str, sources: list[RawSource]) -> str:
    lines = [f"TOPIC: {topic}", f"LEARNER INTENT: {intent}", "", "READING LIST:"]
    for s in sources:
        lines.append(f"- [{s.tier}] {s.title} ({s.url}) — {s.summary}".rstrip(" —"))
    return "\n".join(lines)


def _parse_foundation_json(text: str) -> Foundation:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip()
    data = json.loads(cleaned)
    return Foundation(
        overview=str(data.get("overview", "")),
        key_concepts=list(data.get("key_concepts", [])),
        prerequisite_map=dict(data.get("prerequisite_map", {})),
    )


def synthesize_foundation(
    topic: str, intent: str, sources: list[RawSource], llm: LLMClient
) -> Foundation:
    """Single structured LLM call → Foundation (overview + concepts + prereq map)."""
    user_msg = _build_foundation_user_msg(topic, intent, sources)
    resp = llm.complete(
        system=_FOUNDATION_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        tools=[],
    )
    return _parse_foundation_json(resp.text)
