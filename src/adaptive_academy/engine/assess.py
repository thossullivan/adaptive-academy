import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

from sqlmodel import Session, col, select

from adaptive_academy.engine.grade_gate import checked_completion
from adaptive_academy.engine.output_checks import GRADE_RUBRIC, CheckContext
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    Deliverable,
    Item,
    KnowledgeEstimate,
    ReferenceAnchor,
    Rubric,
    SourceDoc,
    TopicFoundation,
)
from adaptive_academy.prompts import GRADE, PROBE_TEXT, RUBRIC
from adaptive_academy.engine.untrusted import escape_markers

# Deterministic band ceilings (a missing required element or a present misconception means the
# explanation cannot be graded "solid"). Applied as a CEILING, not a subtraction, so the LLM's
# band and the rules can never disagree into an arbitrary float.
_OMISSION_CEIL = 0.70
_MISCONCEPTION_CEIL = 0.50
_NO_MECHANISM_CEIL = 0.50  # the illusion-of-competence cap

# The assessment kinds whose grade writes the concept's KnowledgeEstimate (in assess_concept,
# below). Their callers: the /assess route (self_explanation, calibration, source_quiz),
# decay.grade_decay_check (recall), roleplay.grade_roleplay (roleplay),
# paper_probe.grade_paper_probe (paper_probe). The stored estimate is the concept's GRADE only when at least one of these
# exists: the curriculum seeds every concept with a prior (level "high"), and a prior is not a
# grade. Kinds that never write the estimate, and so never make it a grade:
#   teach, productive_failure  (their own engines; corroborating signals, not grades)
#   artifact_review            (the "shipped" signal: engine/artifact.py writes it per phase
#                               concept without touching the estimate, and assess_concept
#                               below skips the estimate for it too, so one high-scoring
#                               review can't be both the grade and its own corroboration)
GRADING_KINDS = frozenset(
    {"self_explanation", "calibration", "source_quiz", "recall", "roleplay", "paper_probe"})
ASSESSABLE_KINDS = GRADING_KINDS | {"artifact_review"}  # what assess_concept accepts


def graded_concept_ids(session: Session, concept_ids: list[int]) -> set[int]:
    """The concepts (of these) whose stored KnowledgeEstimate is a real grade: at least one
    assessment of a GRADING_KINDS kind. Every other concept's estimate is only a prior."""
    if not concept_ids:
        return set()
    return set(session.exec(
        select(Assessment.concept_id).where(
            col(Assessment.concept_id).in_(concept_ids),
            col(Assessment.kind).in_(GRADING_KINDS),
        ).distinct()).all())


class AnchorError(Exception):
    """No ReferenceAnchor available for a source_quiz probe (route maps to HTTP 400)."""


class AssessKindError(ValueError):
    """An assessment kind assess_concept doesn't grade (route maps to HTTP 400)."""


def level_from_score(score: float) -> tuple[str, float]:
    """Map an anchored score (0..1) to a KnowledgeEstimate level + confidence.

    Thresholds are empirical (tune here): >=0.75 high, >=0.45 medium, else low.
    """
    s = max(0.0, min(1.0, score))
    level = "high" if s >= 0.75 else "medium" if s >= 0.45 else "low"
    return level, round(s, 2)


def compute_delta(score: float, baseline_score: float | None) -> float | None:
    if baseline_score is None:
        return None
    return round(score - baseline_score, 4)


# ── Anchor-term matching ─────────────────────────────────────────────────────
# Rubric must_include / weak_signs (and a source anchor's key_points) are matched against the
# learner's text. Both sides are first normalised to an ASCII form, so X^T matches Xᵀ and
# "Chain-Rule!" matches "chain rule". A formula-like item is never a hard gap: a correct answer
# may use other variable names (w for θ) or another convention (MSE without ½), which no
# literal match can tell from a wrong one, so the grader judges it instead.

# Unicode math notation -> ASCII. Spaced where the ASCII is a word ("grad J" for ∇J).
_MATH_CHARS = {
    "−": "-", "∓": "-+", "±": "+-", "‖": "||", "∥": "||", "∣": "|", "×": "*", "·": "*",
    "⋅": "*", "∗": "*", "÷": "/", "∕": "/", "⁄": "/", "√": " sqrt ", "∇": " grad ",
    "∂": " d ", "∑": " sum ", "∏": " prod ", "∫": " int ", "≤": "<=", "⩽": "<=", "≥": ">=",
    "⩾": ">=", "≠": "!=", "≈": "~", "∼": "~", "≃": "~", "∝": "~", "≡": "=", "≔": ":=",
    "→": "->", "⟶": "->", "←": "<-", "⇒": "=>", "∞": " inf ", "∈": " in ", "⊤": "^T",
    "ᵀ": "^T", "′": "'", "″": "''", "⟨": "<", "⟩": ">",
}
# Prose typography -> ASCII. Not notation: an en dash in "Gauss–Newton" is not a minus sign.
_TEXT_CHARS = {
    **dict.fromkeys("‐‑‒–—―", "-"), **dict.fromkeys("‘’‚‛", "'"), **dict.fromkeys("“”„‟", '"'),
    **dict.fromkeys("     ", " "), "…": "...", "​": "",
}
_GREEK_VARIANTS = {"ϑ": "theta", "ϕ": "phi", "ϵ": "epsilon", "ϖ": "pi", "ϱ": "rho",
                   "ϰ": "kappa", "µ": "mu"}
# Lower-case tokens that are notation, not words a learner would say (Greek letter names
# come from normalising θ etc.; the rest are function names in formulas).
_MATH_WORDS = frozenset({
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa",
    "lambda", "mu", "nu", "xi", "omicron", "pi", "rho", "sigma", "tau", "upsilon", "phi",
    "chi", "psi", "omega", "sqrt", "exp", "log", "sin", "cos", "tan", "tanh", "max", "min",
    "argmax", "argmin", "sum", "prod", "det", "grad", "nabla", "var", "cov", "inf", "sup",
    "lim", "mod", "diag", "int",
})
_STOPWORDS = frozenset({"the", "and", "for", "via", "with", "are", "its", "from", "that",
                        "this", "into", "onto", "than"})


@lru_cache(maxsize=4096)
def _char_ascii(c: str) -> tuple[str, bool]:
    """One character's ASCII form, and whether it is math notation."""
    if c.isascii():
        return c, False
    if c in _TEXT_CHARS:
        return _TEXT_CHARS[c], False
    if c in _MATH_CHARS:
        return _MATH_CHARS[c], True
    if c in _GREEK_VARIANTS:
        return f" {_GREEK_VARIANTS[c]} ", True
    name = unicodedata.name(c, "")
    words = name.split()
    if name.startswith("GREEK") and "LETTER" in words:
        rest = [w for w in words[words.index("LETTER") + 1:] if w != "FINAL"]
        if rest:
            return f" {rest[0].lower()} ", True
    folded = unicodedata.normalize("NFKC", c)
    if folded != c:
        base = _ascii(folded)
        if "SUPERSCRIPT" in name or name.startswith("MODIFIER LETTER"):
            if base and (base.isalnum() or base in "+-=()"):
                return f"^{base}", True
        elif "SUBSCRIPT" in name:
            return f"_{base}", True
        else:  # ½ -> 1/2, fullwidth digits, ligatures
            return base, unicodedata.category(c) in ("Sm", "No")
    if unicodedata.category(c).startswith("L"):  # é -> e, so "naïve" matches "naive"
        stripped = "".join(ch for ch in unicodedata.normalize("NFKD", c)
                           if not unicodedata.combining(ch))
        if stripped.isascii() and stripped:
            return stripped, False
    return c, unicodedata.category(c) == "Sm"


def _ascii(s: str) -> str:
    return "".join(_char_ascii(c)[0] for c in s)


def normalize_math(s: str) -> str:
    """Lower-cased ASCII form of text with Unicode math in it: Xᵀ -> x^t, θ -> theta,
    ½ -> 1/2, ‖ -> ||, − -> -, x² -> x^2, x₁ -> x_1. Whitespace is left for the caller."""
    return _ascii(s).lower()


def _formula_key(s: str) -> str:
    return "".join(normalize_math(s).split())


def _word_tokens(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize_math(s))


def is_formula_like(item: str) -> bool:
    """Whether a rubric item is notation (checked by the grader) rather than words (checked
    here). Formula-like when, after normalisation, it has ANY notation in it:
      - a Unicode math character (Greek letter, superscript/subscript, ∇ ‖ − ½ ...),
      - an ASCII operator or bracket: ^ _ = + * \\ | < > ~ { } [ ], or a / that is not
        between two words ("and/or" is prose, "1/m" is not),
      - a function call shape, a letter or digit directly before "(" ("f(x)", "sqrt(d)"),
      - a minus between single symbols ("x - y", "x-y") or a spaced minus; a hyphenated
        word ("p-value", "k-means", "top-1") is not one,
    or when it has no natural-language word at all (no token of 3+ letters other than a
    Greek letter name or a function name like sqrt/log/max), e.g. "x theta", "KL"."""
    if any(_char_ascii(c)[1] for c in item):
        return True
    norm = normalize_math(item)
    if re.search(r"[\^_=+*\\|<>~{}\[\]]", norm):
        return True
    if re.search(r"/", re.sub(r"[a-z]{3,}/(?=[a-z]{3,})", " ", norm)):
        return True
    if re.search(r"[a-z0-9]\(", norm):
        return True
    if re.search(r"\b[a-z0-9]\s*-\s*[a-z0-9]\b", norm) or re.search(r"\s-\s", norm):
        return True
    return not any(len(t) >= 3 and t not in _MATH_WORDS for t in re.findall(r"[a-z]+", norm))


def _has_words(item: str, text_tokens: list[str], text_key: str) -> bool:
    """A word item is present when its phrase appears in the text, or when every one of its
    content words does (in any order): "squared error" matches "the error, squared". Each
    word is a substring match, as the phrase always was, so "residual" matches "residuals"."""
    tokens = _word_tokens(item)
    if not tokens:
        return True
    if " ".join(tokens) in text_key:
        return True
    content = [t for t in tokens if len(t) >= 3 and t not in _STOPWORDS] or tokens
    return all(t in text_key for t in content)


def _has_phrase(item: str, text_key: str) -> bool:
    """A weak sign is present only as whole words, so "memory" is not in "memoryless"."""
    tokens = _word_tokens(item)
    return bool(tokens) and f" {' '.join(tokens)} " in f" {text_key} "


@dataclass
class RulesCheck:
    """The deterministic anchor checks on one response."""

    gaps: list[str] = field(default_factory=list)  # hard: they set the score ceilings
    # Formula-like must_include items the text doesn't contain literally, and formula-like
    # weak signs it does: notation-dependent either way, so left to the grader, not capped.
    formulas_unmatched: list[str] = field(default_factory=list)
    formula_signs_present: list[str] = field(default_factory=list)

    @property
    def left_to_grader(self) -> list[str]:
        return self.formulas_unmatched + self.formula_signs_present


def check_anchor_terms(response: str, must_include: list[str],
                       weak_signs: list[str]) -> RulesCheck:
    """Deterministic anchor checks (§2.3): the LLM grader cannot paper over these. Word items
    are hard checks; formula-like items (is_formula_like) are soft notes for the grader."""
    text_tokens = _word_tokens(response or "")
    text_key = " ".join(text_tokens)
    text_formula = _formula_key(response or "")
    result = RulesCheck()
    for term in must_include:
        if not term or not term.strip():
            continue
        if is_formula_like(term):
            if _formula_key(term) not in text_formula:
                result.formulas_unmatched.append(term)
        elif not _has_words(term, text_tokens, text_key):
            result.gaps.append(f"omitted required element: {term}")
    for sign in weak_signs:
        if not sign or not sign.strip():
            continue
        if is_formula_like(sign):
            if _formula_key(sign) in text_formula:
                result.formula_signs_present.append(sign)
        elif _has_phrase(sign, text_key):
            result.gaps.append(f"contains likely misconception: {sign}")
    return result


def apply_rules_checks(response: str, must_include: list[str], weak_signs: list[str]) -> list[str]:
    """The hard gaps of check_anchor_terms: the ones penalize_score turns into ceilings."""
    return check_anchor_terms(response, must_include, weak_signs).gaps


def penalize_score(llm_score: float, rules_gaps: list[str]) -> float:
    """Apply deterministic anti-sycophancy CEILINGS (not subtractions): a missing required
    element caps the grade at 'developing-with-gaps'; a present misconception caps it lower."""
    s = max(0.0, min(1.0, llm_score))
    if any(g.startswith("omitted required element") for g in rules_gaps):
        s = min(s, _OMISSION_CEIL)
    if any(g.startswith("contains likely misconception") for g in rules_gaps):
        s = min(s, _MISCONCEPTION_CEIL)
    return round(s, 4)


@dataclass
class RubricDraft:
    criteria: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    strong_signs: list[str] = field(default_factory=list)
    weak_signs: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)


@dataclass
class GradeDraft:
    score: float = 0.0
    verdict: str = ""
    gaps: list[str] = field(default_factory=list)
    confidence_actual: float | None = None
    # The grader's self-report of whether a real causal mechanism was demonstrated. Defaults
    # True so an older/absent value never wrongly caps; a false value triggers the 0.50 cap.
    mechanism_present: bool = True



def _as_float(v, default: float | None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_rubric_json(text: str) -> RubricDraft:
    d = json.loads(extract_json(text))
    return RubricDraft(
        criteria=list(d.get("criteria", []) or []),
        must_include=list(d.get("must_include", []) or []),
        strong_signs=list(d.get("strong_signs", []) or []),
        weak_signs=list(d.get("weak_signs", []) or []),
        source_refs=list(d.get("source_refs", []) or []),
    )


def grade_from_dict(d: dict) -> GradeDraft:
    """A GradeDraft from a grader answer. Lenient on its own; graders run it only on answers
    that passed output_checks.GRADE_RUBRIC, which is what makes the values trustworthy."""
    return GradeDraft(
        score=_as_float(d.get("score"), 0.0) or 0.0,
        verdict=str(d.get("verdict", "")),
        gaps=list(d.get("gaps", []) or []),
        confidence_actual=_as_float(d.get("confidence_actual"), None),
        mechanism_present=bool(d.get("mechanism_present", True)),
    )


def parse_grade_json(text: str) -> GradeDraft:
    return grade_from_dict(json.loads(extract_json(text)))


def build_rubric_prompt(concept_name: str, foundation: TopicFoundation | None,
                        sources: list[SourceDoc]) -> tuple[str, str]:
    lines = [f"CONCEPT: {concept_name}"]
    if foundation:
        lines.append(f"FOUNDATION OVERVIEW: {foundation.overview}")
        lines.append(f"KEY CONCEPTS: {', '.join(foundation.key_concepts)}")
    if sources:
        lines.append("SOURCES:")
        for s in sources:
            lines.append(f"- [{s.tier}] {s.title} — {s.summary}".rstrip(" —"))
    return RUBRIC, "\n".join(lines)


def ensure_rubric(session: Session, concept: Concept, *, llm: LLMClient) -> Rubric:
    """Get the concept's rubric, generating + caching it on first use (§2.1)."""
    from adaptive_academy.engine.memory import topic_id_for_concept

    existing = session.exec(select(Rubric).where(Rubric.concept_id == concept.id)).first()
    if existing is not None:
        return existing
    topic_id = topic_id_for_concept(session, concept.id)
    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)).first()
    sources = session.exec(
        select(SourceDoc).where(SourceDoc.topic_id == topic_id,
                                SourceDoc.status == "accepted")).all()
    system, user = build_rubric_prompt(concept.name, foundation, sources)
    resp = llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[])
    draft = parse_rubric_json(resp.text)
    rubric = Rubric(concept_id=concept.id, criteria=draft.criteria,
                    must_include=draft.must_include, strong_signs=draft.strong_signs,
                    weak_signs=draft.weak_signs, source_refs=draft.source_refs)
    session.add(rubric)
    session.commit()
    session.refresh(rubric)
    return rubric


@dataclass
class AssessmentResult:
    assessment: Assessment
    estimate: KnowledgeEstimate | None  # None for a kind outside GRADING_KINDS (no grade)
    events: list[AgentEvent]


def build_grade_prompt(concept_name: str, kind: str, criteria: list[str],
                       reference: str, response: str, *,
                       formulas: list[str] | None = None,
                       formula_signs: list[str] | None = None) -> tuple[str, str]:
    """`formulas` / `formula_signs`: the formula-like must_include items and weak signs the
    rules checks left to the grader (check_anchor_terms), judged here by meaning."""
    lines = [f"CONCEPT: {concept_name}", f"PROBE KIND: {kind}", "", "RUBRIC / ANCHOR:"]
    for c in criteria:
        lines.append(f"- {c}")
    if formulas:
        lines.append("EXPECTED FORMULAS (judge by meaning: equivalent notation, other variable "
                     "names, or another convention such as a constant factor all count):")
        lines += [f"- {f}" for f in formulas]
    if formula_signs:
        lines.append("POSSIBLE MISCONCEPTIONS IN NOTATION (a gap only if the answer actually "
                     "commits one, not when the text appears inside a correct expression):")
        lines += [f"- {s}" for s in formula_signs]
    if reference:
        lines.append(f"REFERENCE ANSWER: {reference}")
    lines += ["", "<<<RESPONSE>>>", escape_markers(response or "(empty)"), "<<<END_RESPONSE>>>"]
    return GRADE, "\n".join(lines)


def _deliverable_criteria(session: Session, item_id: int | None) -> list[str]:
    if item_id is None:
        return []
    item = session.get(Item, item_id)
    if item is None:
        return []
    d = session.exec(select(Deliverable).where(Deliverable.phase_id == item.phase_id)).first()
    return d.acceptance_criteria if d else []


def _resolve_anchor(session: Session, concept: Concept,
                    anchor_id: int | None) -> ReferenceAnchor:
    if anchor_id is not None:
        anchor = session.get(ReferenceAnchor, anchor_id)
        # Don't let a caller grade one concept against another concept's anchor.
        # A topic-wide anchor (concept_id is None) is allowed for any concept.
        if anchor is not None and anchor.concept_id not in (None, concept.id):
            raise AnchorError("anchor belongs to a different concept")
    else:
        anchor = session.exec(
            select(ReferenceAnchor).where(ReferenceAnchor.concept_id == concept.id)
            .order_by(ReferenceAnchor.id)).first()
    if anchor is None:
        raise AnchorError("no anchor for this concept; generate anchors first")
    return anchor


def _emitter(session: Session, topic_id: int | None, events: list[AgentEvent]):
    def emit(k: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic_id, kind=k, detail=detail)
        session.add(ev)
        events.append(ev)
    return emit


@dataclass
class CheckedGrade:
    """A concept grade whose answer passed its output checks. Nothing is written yet:
    record_grade turns it into an Assessment row (and, for GRADING_KINDS, the estimate)."""

    concept: Concept
    kind: str
    response: str
    probe: str
    grade: GradeDraft
    rules_gaps: list[str]
    topic_id: int | None
    rubric_id: int | None = None
    anchor_id: int | None = None
    item_id: int | None = None
    confidence_predicted: float | None = None
    baseline_id: int | None = None
    events: list[AgentEvent] = field(default_factory=list)
    # GRADE's tag, or "GRADE-tag+GRADE_CORRECTION-tag" when the answer was regenerated.
    prompt_tag: str = GRADE.tag


def grade_concept(
    session: Session,
    concept: Concept,
    kind: str,
    response: str,
    *,
    llm: LLMClient,
    confidence_predicted: float | None = None,
    baseline_id: int | None = None,
    item_id: int | None = None,
    anchor_id: int | None = None,
) -> CheckedGrade:
    """Run the anchored probe's grader call through its output checks. Writes trace events
    (and, on first use, the concept's rubric) but no Assessment row and no estimate; a grade
    that fails its checks twice raises GradeCheckError (`invalid_output`)."""
    from adaptive_academy.engine.memory import topic_id_for_concept

    if kind not in ASSESSABLE_KINDS:
        raise AssessKindError(
            f"unknown assessment kind {kind!r}; expected one of {sorted(ASSESSABLE_KINDS)}")

    events: list[AgentEvent] = []
    topic_id = topic_id_for_concept(session, concept.id)
    emit = _emitter(session, topic_id, events)

    # Resolve the anchor (rubric vs. acceptance criteria) and the probe text.
    rubric_id: int | None = None
    anchor_ref_id: int | None = None
    must_include: list[str] = []
    weak_signs: list[str] = []
    reference = ""
    if kind == "artifact_review":
        criteria = _deliverable_criteria(session, item_id)
        probe = PROBE_TEXT[kind].format(concept=concept.name)
    elif kind == "source_quiz":
        anchor = _resolve_anchor(session, concept, anchor_id)
        anchor_ref_id = anchor.id
        criteria = anchor.key_points
        must_include = anchor.key_points
        reference = anchor.reference_answer
        probe = anchor.question
    else:
        rubric = ensure_rubric(session, concept, llm=llm)
        rubric_id = rubric.id
        criteria, must_include, weak_signs = rubric.criteria, rubric.must_include, rubric.weak_signs
        probe = PROBE_TEXT.get(kind, PROBE_TEXT["self_explanation"]).format(
            concept=concept.name, question=concept.name)
    emit("assess:probe", kind)

    rules = check_anchor_terms(response, must_include, weak_signs)
    rules_gaps = rules.gaps
    if rules.left_to_grader:
        emit("assess:rules-soft",
             f"{len(rules.left_to_grader)} formula item(s) left to the grader: "
             + "; ".join(rules.left_to_grader))
    emit("prompt", GRADE.tag)
    system, user = build_grade_prompt(
        concept.name, kind, criteria, reference, response,
        formulas=[t for t in rules.formulas_unmatched if t not in criteria],
        formula_signs=rules.formula_signs_present)
    answer = checked_completion(
        session, llm, system=system, user=user, rubric=GRADE_RUBRIC, emit=emit,
        ctx=CheckContext(rules_gaps=tuple(rules_gaps)))
    return CheckedGrade(
        concept=concept, kind=kind, response=response, probe=probe,
        grade=grade_from_dict(answer.data), rules_gaps=rules_gaps, topic_id=topic_id,
        rubric_id=rubric_id, anchor_id=anchor_ref_id, item_id=item_id,
        confidence_predicted=confidence_predicted, baseline_id=baseline_id, events=events,
        prompt_tag=answer.prompt_tag(GRADE))


def record_grade(
    session: Session,
    checked: CheckedGrade,
    *,
    retriever: Retriever | None = None,
) -> AssessmentResult:
    """Write a checked grade: the Assessment row and, for GRADING_KINDS, the estimate.
    Flushes but does not commit, so a caller can write several grades atomically."""
    from adaptive_academy.engine.memory import index_assessment

    concept, kind, grade, rules_gaps = (
        checked.concept, checked.kind, checked.grade, checked.rules_gaps)
    events = checked.events
    emit = _emitter(session, checked.topic_id, events)

    if rules_gaps:
        emit("assess:rules", f"{len(rules_gaps)} hard gap(s)")
    # Code-enforced illusion-of-competence cap: fluent prose with no demonstrated mechanism
    # cannot score above 'developing', no matter what the LLM returned (defense in depth).
    score = grade.score
    if not grade.mechanism_present:
        score = min(score, _NO_MECHANISM_CEIL)
        emit("assess:mechanism", "capped: no mechanism demonstrated")
    final_score = penalize_score(score, rules_gaps)
    gaps = list(grade.gaps) + rules_gaps
    emit("assess:graded", f"score={final_score}")

    baseline_id = checked.baseline_id
    baseline = session.get(Assessment, baseline_id) if baseline_id else None
    delta = compute_delta(final_score, baseline.score if baseline else None)
    confidence_actual = final_score if kind == "calibration" else grade.confidence_actual

    assessment = Assessment(
        concept_id=concept.id, item_id=checked.item_id, kind=kind, prompt=checked.probe,
        response=checked.response, verdict=grade.verdict, score=final_score, gaps=gaps,
        confidence_predicted=checked.confidence_predicted, confidence_actual=confidence_actual,
        rubric_id=checked.rubric_id, anchor_id=checked.anchor_id,
        baseline_assessment_id=baseline_id, delta=delta,
        prompt_tag=checked.prompt_tag)  # the grading prompt(s), as traced (not RUBRIC)
    session.add(assessment)
    session.flush()
    index_assessment(session, assessment, topic_id=checked.topic_id, retriever=retriever)

    estimate: KnowledgeEstimate | None = None
    if kind in GRADING_KINDS:
        level, conf = level_from_score(final_score)
        estimate = session.exec(
            select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept.id)).first()
        if estimate is None:
            estimate = KnowledgeEstimate(concept_id=concept.id)
            session.add(estimate)
        estimate.level, estimate.confidence = level, conf
        emit("assess:estimate", f"level={level}")

    emit("assess:done", f"concept {concept.id}")
    session.flush()
    return AssessmentResult(assessment=assessment, estimate=estimate, events=events)


def assess_concept(
    session: Session,
    concept: Concept,
    kind: str,
    response: str,
    *,
    llm: LLMClient,
    confidence_predicted: float | None = None,
    baseline_id: int | None = None,
    item_id: int | None = None,
    anchor_id: int | None = None,
    retriever: Retriever | None = None,
) -> AssessmentResult:
    """Run an anchored probe, persist an Assessment, and (for GRADING_KINDS) update the
    KnowledgeEstimate. Fails closed: a grade that fails its output checks twice raises
    GradeCheckError before anything is written."""
    checked = grade_concept(
        session, concept, kind, response, llm=llm,
        confidence_predicted=confidence_predicted, baseline_id=baseline_id,
        item_id=item_id, anchor_id=anchor_id)
    result = record_grade(session, checked, retriever=retriever)
    session.commit()
    session.refresh(result.assessment)
    if result.estimate is not None:
        session.refresh(result.estimate)
    return result
