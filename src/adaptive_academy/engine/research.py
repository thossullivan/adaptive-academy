import json
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit

from sqlmodel import Session

from adaptive_academy.engine.fanout import fan_out_with_retry
from adaptive_academy.engine.memory import (
    ALREADY_COVERED_MARKER,
    DEFAULT_K,
    INJECT_BUDGET_CHARS,
    retrieve,
)
from adaptive_academy.llm.researcher_types import RawSource, ResearcherClient, SearchBrief
from adaptive_academy.llm.retriever_types import Hit, Retriever
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.prompts import RESEARCH_FOUNDATION
from adaptive_academy.models import AgentEvent, SourceDoc, Topic, TopicFoundation, TopicIntent

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


@dataclass
class Foundation:
    overview: str
    key_concepts: list[str]
    prerequisite_map: dict


def _build_foundation_user_msg(
    topic: str,
    intent: str,
    sources: list[RawSource],
    *,
    covered_block: str = "",
) -> str:
    lines = [f"TOPIC: {topic}", f"LEARNER INTENT: {intent}", "", "<<<SOURCES>>>"]
    for s in sources:
        lines.append(f"- [{s.tier}] {s.title} ({s.url}) — {s.summary}".rstrip(" —"))
    lines.append("<<<END_SOURCES>>>")
    if covered_block:
        lines.extend(["", covered_block])
    return "\n".join(lines)


def _parse_foundation_json(text: str) -> Foundation:
    data = json.loads(extract_json(text))
    return Foundation(
        overview=str(data.get("overview", "")),
        key_concepts=list(data.get("key_concepts", [])),
        prerequisite_map=dict(data.get("prerequisite_map", {})),
    )


def synthesize_foundation(
    topic: str,
    intent: str,
    sources: list[RawSource],
    llm: LLMClient,
    *,
    covered_block: str = "",
) -> Foundation:
    """Single structured LLM call → Foundation (overview + concepts + prereq map)."""
    user_msg = _build_foundation_user_msg(
        topic,
        intent,
        sources,
        covered_block=covered_block,
    )
    resp = llm.complete(
        system=RESEARCH_FOUNDATION,
        messages=[{"role": "user", "content": user_msg}],
        tools=[],
    )
    return _parse_foundation_json(resp.text)


@dataclass
class ResearchResult:
    foundation: TopicFoundation
    sources: list[SourceDoc]
    events: list[AgentEvent]


def research_topic(
    session: Session,
    topic: Topic,
    intent: TopicIntent,
    *,
    researcher: ResearcherClient,
    llm: LLMClient,
    max_subagents: int = 5,
    cap: int = 12,
    max_workers: int = 5,
    retriever: Retriever | None = None,
) -> ResearchResult:
    """Fan out over briefs, dedupe+rank, synthesize a foundation, persist, and trace."""
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    briefs = build_briefs(topic.title, intent.goal, max_subagents)
    emit("research:plan", f"{len(briefs)} briefs")

    # Fan out concurrently (results kept in brief order for deterministic tracing);
    # a failed angle must not abort the run and gets one second-chance pass.
    per_brief, failures, recovered = fan_out_with_retry(briefs, researcher, max_workers)

    raw: list[RawSource] = []
    for i, brief in enumerate(briefs):
        found = per_brief[i]
        for s in found:
            s.angle = brief.angle
        if i in failures:
            emit("research:subagent_error", f"{brief.angle}: {failures[i]}")
        elif i in recovered:
            emit("research:subagent_retry", f"{brief.angle}: recovered {recovered[i]} sources")
        else:
            emit("research:subagent", f"{brief.angle}: {len(found)} sources")
        raw.extend(found)

    deduped = dedupe_by_url(raw)
    ranked = rank_sources(deduped)
    kept, dropped = ranked[:cap], ranked[cap:]
    if dropped:
        emit("research:capped", f"dropped {len(dropped)} of {len(ranked)}")

    covered_block = ""
    if retriever is not None:
        vault_hits = retrieve(
            session,
            retriever,
            topic.title,
            kinds=("vault_note",),
            topic_id=topic.id,
            k=DEFAULT_K,
            event_target={"topic_id": topic.id},
        )
        covered_block = _vault_heading_block(vault_hits)

    emit("prompt", RESEARCH_FOUNDATION.tag)
    foundation_data = synthesize_foundation(
        topic.title,
        intent.goal,
        kept,
        llm,
        covered_block=covered_block,
    )
    emit("research:synth", f"{len(foundation_data.key_concepts)} key concepts")

    source_rows: list[SourceDoc] = []
    for idx, s in enumerate(kept):
        row = SourceDoc(
            topic_id=topic.id,
            title=s.title,
            url=s.url,
            tier=s.tier,
            summary=s.summary,
            why=s.why,
            relevance=s.relevance,
            rank=idx,
            angle=s.angle,
            status="proposed",
        )
        session.add(row)
        source_rows.append(row)

    foundation = TopicFoundation(
        topic_id=topic.id,
        overview=foundation_data.overview,
        key_concepts=foundation_data.key_concepts,
        prerequisite_map=foundation_data.prerequisite_map,
    )
    session.add(foundation)
    emit("research:done", f"{len(source_rows)} sources proposed")
    session.commit()

    for row in source_rows:
        session.refresh(row)
    session.refresh(foundation)
    return ResearchResult(foundation=foundation, sources=source_rows, events=events)


def _vault_heading_block(hits: list[Hit]) -> str:
    opening = f"<<<{ALREADY_COVERED_MARKER}>>>"
    closing = f"<<<END_{ALREADY_COVERED_MARKER}>>>"
    headings: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        heading = (hit.chunk.heading or hit.chunk.context).strip()
        if not heading or heading in seen:
            continue
        candidate_headings = [*headings, heading]
        candidate = (
            f"{opening}\n"
            + "\n".join(f"- {item}" for item in candidate_headings)
            + f"\n{closing}"
        )
        if len(candidate) > INJECT_BUDGET_CHARS:
            break
        seen.add(heading)
        headings.append(heading)
    if not headings:
        return ""
    return (
        f"{opening}\n"
        + "\n".join(f"- {heading}" for heading in headings)
        + f"\n{closing}"
    )
