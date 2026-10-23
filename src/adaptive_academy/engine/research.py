import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit

from sqlmodel import Session, select

from adaptive_academy.engine import concept_names
from adaptive_academy.engine.fanout import fan_out_with_retry
from adaptive_academy.engine.runlock import exclusive_run
from adaptive_academy.engine.memory import (
    ALREADY_COVERED_MARKER,
    DEFAULT_K,
    INJECT_BUDGET_CHARS,
    escape_markers,
    retrieve,
)
from adaptive_academy.llm.researcher_types import RawSource, ResearcherClient, SearchBrief
from adaptive_academy.llm.retriever_types import Hit, Retriever
from adaptive_academy.jsonout import extract_json, require_object, text_items
from adaptive_academy.llm.types import LLMClient, StructuredOutputError
from adaptive_academy.prompts import CONCEPT_NAME_CORRECTION, RESEARCH_FOUNDATION
from adaptive_academy.models import (
    AgentEvent,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
    Track,
)

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


# The web-search citation form only: `<cite index='20-11'>` or `<cite index="1-1">` (seen
# leaked as `(cite index=...>` too). A plain `<cite>` is real HTML and is left alone.
_SEARCH_CITE_OPEN = r"""[<(]cite\s+index\s*=\s*(?:'[^'<>]*'|"[^"<>]*")\s*>"""
_CITE_TOKEN = re.compile(
    rf"(?P<search>{_SEARCH_CITE_OPEN})|(?P<open><cite\b[^>]*>)|(?P<close></cite\s*>)",
    re.IGNORECASE,
)


def strip_cite_tags(text: str) -> str:
    """Drop web-search citation tags (`<cite index='20-11'>…</cite>`), keeping the text inside.

    The search tool's citations sometimes leak into the model's JSON strings; they are markup
    for the API, not words for the learner. Only the `index=` form is removed, with the
    `</cite>` that closes it; any other `<cite>` and its closing tag stay as written.
    """
    if "cite" not in text.casefold():
        return text
    out: list[str] = []
    # One entry per open <cite>: True when it was a search citation (its </cite> goes too).
    stack: list[bool] = []
    last = 0
    for match in _CITE_TOKEN.finditer(text):
        out.append(text[last:match.start()])
        last = match.end()
        if match.group("search"):
            stack.append(True)
        elif match.group("open"):
            stack.append(False)
            out.append(match.group(0))
        elif not (stack and stack.pop()):
            out.append(match.group(0))
    out.append(text[last:])
    return "".join(out)


def clean_source(s: RawSource) -> RawSource:
    """Strip citation tags from every text field of a raw source, in place."""
    s.title = strip_cite_tags(s.title)
    s.summary = strip_cite_tags(s.summary)
    s.why = strip_cite_tags(s.why)
    return s


_TRAILING_PARENTHETICAL = re.compile(r"\s*\(([^()]*)\)\s*$")
# Words that say nothing about which work a parenthetical names: two "(Part V, 2018)" and
# "(Part VI, 2018)" share "part" but are different parts.
_GENERIC_PAREN_WORDS = frozenset({
    "part", "chapter", "lecture", "notes", "edition", "vol", "volume", "the", "and", "et", "al",
    "ed", "eds", "arxiv", "pdf", "slides", "video", "course",
    "book", "lesson", "section", "unit", "module", "week", "episode", "appendix",
})
# A shorter key ("introduction", "documentation") is too generic to call two pages the same.
_MIN_TITLE_KEY = 16


def _norm_title(text: str) -> str:
    """Case-folded, with punctuation and whitespace collapsed to single spaces."""
    return " ".join(re.sub(r"[^\w]+", " ", text.casefold()).split())


@dataclass(frozen=True)
class _TitleKey:
    full: str  # the whole title, parenthetical included
    head: str  # the title before a trailing parenthetical (the whole title if there is none)
    paren_words: frozenset[str] | None  # distinctive words in that parenthetical, None if none


def _title_key(title: str) -> _TitleKey:
    match = _TRAILING_PARENTHETICAL.search(title)
    if match is None:
        return _TitleKey(_norm_title(title), _norm_title(title), None)
    words = frozenset(
        w for w in re.findall(r"[^\W\d_]+", match.group(1).casefold())
        if len(w) >= 3 and w not in _GENERIC_PAREN_WORDS
    )
    return _TitleKey(_norm_title(title), _norm_title(title[:match.start()]), words)


def _same_work(a: _TitleKey, b: _TitleKey) -> bool:
    """Two titles name the same work when they match in full, or when the part before a
    trailing parenthetical matches and both parentheticals share a distinctive word (an author:
    "(Deng, Liu, Chen)" and "(Deng, Lu, Chen, 2016)"). "(Kernels)" and "(Support Vector
    Machines)", "(Part V, 2018)" and "(Part VI, 2018)", "(2019)" and "(2020)" stay apart."""
    if len(a.full) >= _MIN_TITLE_KEY and a.full == b.full:
        return True
    return (
        len(a.head) >= _MIN_TITLE_KEY
        and a.head == b.head
        and a.paren_words is not None
        and b.paren_words is not None
        and not a.paren_words.isdisjoint(b.paren_words)
    )


def same_work(a: str, b: str) -> bool:
    """True when two source titles name the same work (see ``_same_work``)."""
    return _same_work(_title_key(a), _title_key(b))


def dedupe_by_title(
    sources: list[RawSource],
    on_drop: Callable[[RawSource, RawSource], None] | None = None,
) -> list[RawSource]:
    """Collapse the same work found under different URLs (e.g. "Paper (Deng, Liu, Chen)" and
    "Paper (Deng, Lu, Chen, 2016)"). Keeps the better tier, else the first; order is kept.
    ``on_drop(dropped, kept)`` is called for every source dropped as a copy."""
    kept: list[RawSource] = []
    keys: list[_TitleKey] = []
    for s in sources:
        key = _title_key(s.title)
        j = next((i for i, k in enumerate(keys) if _same_work(k, key)), None)
        if j is None:
            kept.append(s)
            keys.append(key)
        elif s.tier < kept[j].tier:
            if on_drop is not None:
                on_drop(kept[j], s)
            kept[j], keys[j] = s, key
        elif on_drop is not None:
            on_drop(s, kept[j])
    return kept


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
    # Text-parsed, so nothing guarantees the shape: an answer that isn't an object is a
    # StructuredOutputError (a legible 502), and a wrongly typed part is dropped.
    data = require_object(json.loads(extract_json(text)), "research foundation")
    raw_concepts = data.get("key_concepts")
    key_concepts = text_items(raw_concepts)
    if isinstance(raw_concepts, list) and raw_concepts and not key_concepts:
        # Concepts were sent but none is usable: fail legibly, never an empty topic.
        raise StructuredOutputError(
            "malformed", "research foundation: key_concepts has no usable concept name")
    prerequisite_map = data.get("prerequisite_map")
    return Foundation(
        overview=strip_cite_tags(str(data.get("overview", ""))),
        key_concepts=[strip_cite_tags(c) for c in key_concepts],
        prerequisite_map=({strip_cite_tags(str(k)): [strip_cite_tags(v) for v in text_items(vs)]
                           for k, vs in prerequisite_map.items()}
                          if isinstance(prerequisite_map, dict) else {}),
    )


def _name_report(f: Foundation):
    return concept_names.check_names(
        concept_names.foundation_names(f.key_concepts, f.prerequisite_map))


def synthesize_foundation(
    topic: str,
    intent: str,
    sources: list[RawSource],
    llm: LLMClient,
    *,
    covered_block: str = "",
    emit: Callable[[str, str], None] | None = None,
) -> Foundation:
    """LLM call → Foundation (overview + concepts + prereq map), with checked concept names.

    The names are checked (engine/concept_names.py). On a FAIL the model's answer and a
    CONCEPT_NAME_CORRECTION turn naming the failed rule ids are appended (append-only) and
    the call runs once more; names that still fail (or a retry that does not parse) are
    repaired deterministically and a WARN `concepts:repaired` event is recorded. A name
    problem never fails research: the learner gets short names either way.
    """
    record = emit or (lambda _kind, _detail="": None)
    user_msg = _build_foundation_user_msg(
        topic,
        intent,
        sources,
        covered_block=covered_block,
    )
    messages: list[dict] = [{"role": "user", "content": user_msg}]
    resp = llm.complete(system=RESEARCH_FOUNDATION, messages=messages, tools=[])
    foundation = _parse_foundation_json(resp.text)
    report = _name_report(foundation)
    record("concepts:check", concept_names.summarize_check(report, 1))
    if report.passed:
        return foundation

    record("concepts:regenerated", "after FAIL " + ",".join(dict.fromkeys(report.failed_ids)))
    record("prompt", CONCEPT_NAME_CORRECTION.tag)
    messages = [
        *messages,
        {"role": "assistant", "content": resp.text if resp.text.strip() else "(empty reply)"},
        {"role": "user", "content": concept_names.correction_message(report)},
    ]
    # The retry is optional polish on an answer already paid for (and, in research_topic,
    # after the source fan-out): any failure here — a budget or rate limit, the network, an
    # unparseable or shrunken answer — falls back to repairing the first answer.
    second: Foundation | None = None
    try:
        retry = llm.complete(system=RESEARCH_FOUNDATION, messages=messages, tools=[])
        second = _parse_foundation_json(retry.text)
    except Exception as exc:  # noqa: BLE001 — see above; the first answer is still good
        record("concepts:retry_failed", f"{type(exc).__name__}; repairing the first answer")
    if second is not None and not (
            second.key_concepts and len(second.key_concepts) >= len(foundation.key_concepts)):
        record("concepts:retry_failed",
               f"retry returned {len(second.key_concepts)} key concept(s), first had "
               f"{len(foundation.key_concepts)}; repairing the first answer")
        second = None
    if second is not None:
        foundation = second
        report = _name_report(foundation)
        record("concepts:check", concept_names.summarize_check(report, 2))
        if report.passed:
            return foundation

    fix = concept_names.repair_names(foundation.key_concepts, foundation.prerequisite_map)
    record("concepts:repaired", fix.summary())
    return Foundation(overview=foundation.overview, key_concepts=fix.key_concepts,
                      prerequisite_map=fix.prerequisite_map)


@dataclass
class ResearchResult:
    foundation: TopicFoundation
    sources: list[SourceDoc]
    events: list[AgentEvent]


class ResearchAlreadyDone(RuntimeError):
    """The topic already has a foundation; research runs once per topic."""


def research_can_rerun(session: Session, topic_id: int) -> bool:
    """A topic whose research saved a foundation but found no sources can be researched
    again (the new foundation replaces the old one): there is no reading list to review, so
    the learner is otherwise stuck. Once there are sources or a track, research is done."""
    has_sources = session.exec(
        select(SourceDoc.id).where(SourceDoc.topic_id == topic_id).limit(1)).first() is not None
    has_track = session.exec(
        select(Track.id).where(Track.topic_id == topic_id).limit(1)).first() is not None
    return not has_sources and not has_track


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
    """Fan out over briefs, dedupe+rank, synthesize a foundation, persist, and trace.

    Raises `RunInProgress` when research for this topic is already running.
    """
    with exclusive_run(f"research:{topic.id}"):
        return _research_topic_locked(
            session, topic, intent, researcher=researcher, llm=llm,
            max_subagents=max_subagents, cap=cap, max_workers=max_workers,
            retriever=retriever,
        )


def _research_topic_locked(
    session: Session,
    topic: Topic,
    intent: TopicIntent,
    *,
    researcher: ResearcherClient,
    llm: LLMClient,
    max_subagents: int,
    cap: int,
    max_workers: int,
    retriever: Retriever | None,
) -> ResearchResult:
    if session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)
    ).first() is not None and not research_can_rerun(session, topic.id):
        # TopicFoundation.topic_id is unique; a re-run used to spend the whole
        # fan-out and then fail on commit. Refuse before any paid work.
        raise ResearchAlreadyDone("topic already has a foundation; research runs once per topic")

    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    briefs = build_briefs(topic.title, intent.goal, max_subagents)
    emit("research:plan", f"{len(briefs)} briefs")
    session.commit()  # never hold the SQLite write lock across a network call (F5)

    # Fan out concurrently (results kept in brief order for deterministic tracing);
    # a failed angle must not abort the run and gets one second-chance pass.
    per_brief, failures, recovered = fan_out_with_retry(briefs, researcher, max_workers)

    raw: list[RawSource] = []
    for i, brief in enumerate(briefs):
        found = per_brief[i]
        for s in found:
            s.angle = brief.angle
            clean_source(s)
        if i in failures:
            emit("research:subagent_error", f"{brief.angle}: {failures[i]}")
        elif i in recovered:
            emit("research:subagent_retry", f"{brief.angle}: recovered {recovered[i]} sources")
        else:
            emit("research:subagent", f"{brief.angle}: {len(found)} sources")
        raw.extend(found)

    deduped = dedupe_by_url(raw)
    ranked = dedupe_by_title(
        rank_sources(deduped),
        on_drop=lambda dropped, kept: emit(
            "research:title_deduped",
            f'dropped "{dropped.title}" ({dropped.url}) as the same work as '
            f'"{kept.title}" ({kept.url})'[:500]),
    )
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
    session.commit()  # release the lock before the LLM call (F5)
    foundation_data = synthesize_foundation(
        topic.title,
        intent.goal,
        kept,
        llm,
        covered_block=covered_block,
        emit=emit,
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

    # A rerun after a run that found no sources replaces that run's foundation. Flushed
    # first: topic_id is unique, and the unit of work would insert before it deletes.
    previous = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)).first()
    if previous is not None:
        session.delete(previous)
        session.flush()
        emit("research:rerun", "replaced a foundation that came with no sources")

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
        heading = escape_markers((hit.chunk.heading or hit.chunk.context).strip())
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
