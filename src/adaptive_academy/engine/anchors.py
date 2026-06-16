import json
import re

from adaptive_academy.llm.anchor_types import AnchorBrief, RawAnchor

_WS = re.compile(r"\s+")


def anchor_key(question: str) -> str:
    """Stable dedup signature for an anchor question (lowercased, ws-collapsed, trimmed)."""
    return _WS.sub(" ", question.strip().lower())


def match_concept(name: str, concepts: list[str]) -> str | None:
    """Case-insensitive exact match; returns the canonical concept name or None."""
    target = name.strip().lower()
    for c in concepts:
        if c.strip().lower() == target:
            return c
    return None


def dedupe_anchors(pairs: list[tuple[int, RawAnchor]]) -> list[tuple[int, RawAnchor]]:
    """Collapse duplicates on (source_doc_id, anchor_key(question)); keep first; stable order."""
    seen: set[tuple[int, str]] = set()
    out: list[tuple[int, RawAnchor]] = []
    for source_id, a in pairs:
        if not a.question.strip():
            continue
        key = (source_id, anchor_key(a.question))
        if key in seen:
            continue
        seen.add(key)
        out.append((source_id, a))
    return out


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def parse_anchors_json(text: str) -> list[RawAnchor]:
    data = json.loads(_strip_fences(text))
    out: list[RawAnchor] = []
    for a in (data.get("anchors", []) or []):
        out.append(RawAnchor(
            question=str(a.get("question", "")),
            reference_answer=str(a.get("reference_answer", "")),
            key_points=list(a.get("key_points", []) or []),
            concept_name=str(a.get("concept", a.get("concept_name", "")) or ""),
        ))
    return out


def build_anchor_brief(source, key_concepts: list[str]) -> AnchorBrief:
    """Build a fan-out brief from a SourceDoc row + the topic's key concepts."""
    return AnchorBrief(source_doc_id=source.id, title=source.title,
                       summary=source.summary, url=source.url,
                       key_concepts=list(key_concepts))
