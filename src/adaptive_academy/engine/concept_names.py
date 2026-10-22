"""Named output checks for concept names, and a deterministic repair — pure, no session.

A concept name is shown on the Tutor page and pasted into probes ("Explain *why* {concept}
works", prompts.PROBE_TEXT), so a name that states a formula or a result puts the answer on
screen before the learner has tried. A live run (DeepSeek via OpenRouter) named concepts
"Gradient of the cost: ∇J(θ)=Xᵀ(Xθ−y) (divided by m if using the averaged cost)". The prompts
ask for short noun phrases; these checks make that hold when a model ignores them.

Names come from model output in one place: the research foundation's key_concepts and
prerequisite_map (research.synthesize_foundation). Curriculum turns them into Concept rows,
ConceptAlias canonical names derive from those rows, and anchors / the curriculum's
concept_refs resolve against them. So research checks the names (regenerate once with an
append-only CONCEPT_NAME_CORRECTION turn naming the failed rule ids, then repair), and
curriculum repairs again before it creates Concept rows, for foundations stored earlier.

Rules (same Rule / RuleResult / CheckReport shapes as engine/output_checks.py; all FAIL,
because a failing name is regenerated or repaired, never written as is):

  N1  FAIL  The name is a non-empty string.
  N2  FAIL  The name is short: at most MAX_NAME_WORDS words and MAX_NAME_CHARS characters.
            "A few words" naming the idea; the evidence names ran 15-25 words.
  N3  FAIL  The name holds no formula. A formula character is any Unicode math symbol (Sm:
            = < > ≤ ≥ ∇ ∑ − × ±, except + so "C++" passes), ‖ · ^ \\ $, a super- or subscript
            (² ᵀ ₀ ⁻¹), a vulgar fraction (½), a math-alphanumeric letter (𝐱), or a Greek
            letter outside a hyphenated prefix (λmax, Xθ, a bare α fail; β-VAE, λ-calculus,
            α-β pruning pass). Two ASCII shapes also count: a function application, a letter
            or digit glued to "(" (J(θ), f(x), O(n)), and a slash with a digit on either side
            (1/L, 1/2m; TCP/IP and I/O pass). "L2 norm", "Big-O", "GPT-2", "A* search" pass.
  N4  FAIL  The name is a noun phrase, not "Name: claim": no ";", no spaced dash clause
            (" — ", " – ", " - "), and a ":" only before a short subtitle of at most
            MAX_SUBTITLE_WORDS words ("Sampling: Temperature and Top-k", a demo concept,
            passes; "Stability threshold: guaranteed descent for small steps" fails).
            Hyphenated words ("1-D") pass.
  N5  FAIL  The name states no claim: none of the whole words in CLAIM_VERBS (is, are,
            equals, implies, converges, ...). "Least-squares cost is convex" fails.

Repair (repair_name), for a failing name only — a passing name is returned untouched:
  1. take the first ":" / ";" / spaced-dash segment that has a letter or digit;
  2. drop function-notation tokens ("J(θ)=…", "O(n log n)") whole, then parenthetical groups;
  3. cut at the first claim verb;
  4. glue spaced operators to their operands ("1 / L" -> "1/L"), then drop every token that
     holds a formula and every token with no letter or digit;
  5. cap to MAX_NAME_WORDS words, cutting at the last phrase boundary (a stopword) inside the
     window when the next word continues the phrase, drop trailing stopwords, cap characters;
  6. if nothing passes, use the caller's fallback ("Concept 3").
repair_names applies it across a foundation: every name in key_concepts and the
prerequisite map, case variants of a key concept folded onto it, distinct concepts kept
distinct (" (2)" suffix), and the map rewritten with the new names.
"""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from adaptive_academy.engine.output_checks import (
    FAIL,
    CheckReport,
    Rule,
    RuleResult,
    Rubric,
    summarize,
)
from adaptive_academy.prompts import CONCEPT_NAME_CORRECTION

MAX_NAME_WORDS = 7
MAX_NAME_CHARS = 60

CLAIM_VERBS = frozenset({
    "is", "are", "was", "were", "equals", "equal", "implies", "guarantees", "ensures",
    "yields", "converges", "diverges", "means", "causes", "becomes",
})
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "with", "by", "at",
    "from", "along", "via", "vs", "into", "over", "under", "as", "when", "if", "using",
})

_EXTRA_FORMULA_CHARS = frozenset("‖·^\\$")
_ALLOWED_SM = frozenset("+")
_FUNCTION_APPLICATION = re.compile(r"[^\W_]\(")
_DIGIT_SLASH = re.compile(r"\d\s*/\s*\w|\w\s*/\s*\d")
_GREEK_PREFIX_TOKEN = re.compile(r"^[\wͰ-Ͽ]*(?:-[\wͰ-Ͽ]+)+$")
_SEPARATOR = re.compile(r"\s*:(?=\s*\S)|;|\s[—–-]\s")
_CLAIM_SEPARATOR = re.compile(r";|\s[—–-]\s")
MAX_SUBTITLE_WORDS = 3  # "Sampling: Temperature and Top-k" is a subtitle, not a claim
_PARENTHETICAL = re.compile(r"\s*\([^()]*\)")
_APPLIED_TOKEN = re.compile(r"\S*[^\W_]\([^()]*\)\S*")
_SPACED_OPERATOR = re.compile(r"\s*([/=<>^≤≥≠≈−×·*])\s*")
_WORD = re.compile(r"[^\W_]+")


def _is_greek(ch: str) -> bool:
    return "Ͱ" <= ch <= "Ͽ" or "ἀ" <= ch <= "῿"


def _is_formula_char(ch: str) -> bool:
    if ch in _EXTRA_FORMULA_CHARS:
        return True
    cat = unicodedata.category(ch)
    if cat == "Sm" and ch not in _ALLOWED_SM:
        return True
    if cat == "No":  # superscript / subscript digits, vulgar fractions
        return True
    code = ord(ch)
    return (0x2070 <= code <= 0x209F      # superscripts and subscripts
            or 0x1D2C <= code <= 0x1D6A   # modifier letters (ᵀ, ᵢ)
            or 0x1D400 <= code <= 0x1D7FF)  # mathematical alphanumerics


def _greek_outside_prefix(text: str) -> bool:
    for token in text.split():
        if not any(_is_greek(ch) for ch in token):
            continue
        core = token.strip(",.()[]")
        if not _GREEK_PREFIX_TOKEN.match(core):
            return True
        # every hyphen segment holding a Greek letter must be all Greek (β-VAE, not θ1-x)
        for seg in core.split("-"):
            if any(_is_greek(ch) for ch in seg) and not all(_is_greek(ch) for ch in seg):
                return True
    return False


def formula_problem(text: str) -> str | None:
    """What makes `text` a formula, or None."""
    bad = sorted({ch for ch in text if _is_formula_char(ch)})
    if bad:
        return "formula symbols " + " ".join(bad)
    if _greek_outside_prefix(text):
        return "a Greek-letter symbol"
    if _FUNCTION_APPLICATION.search(text):
        return "function notation like f(x)"
    if _DIGIT_SLASH.search(text):
        return "a fraction like 1/L"
    return None


def _words(text: str) -> list[str]:
    return text.split()


# ── Rules ────────────────────────────────────────────────────────────────────

def _quoted(name: Any) -> str:
    text = name if isinstance(name, str) else repr(name)
    return f'"{text[:57]}…"' if len(text) > 60 else f'"{text}"'


def _n1(d, _ctx):
    name = d["name"]
    if not isinstance(name, str):
        return f"{_quoted(name)} is {type(name).__name__}, not a string"
    if not name.strip():
        return "a concept name is empty"
    return None


def _n2(d, _ctx):
    name = d["name"]
    if not isinstance(name, str) or not name.strip():
        return None
    words, chars = len(_words(name)), len(name.strip())
    if words > MAX_NAME_WORDS or chars > MAX_NAME_CHARS:
        return (f"{_quoted(name)} has {words} words / {chars} characters "
                f"(max {MAX_NAME_WORDS} / {MAX_NAME_CHARS})")
    return None


def _n3(d, _ctx):
    name = d["name"]
    if not isinstance(name, str):
        return None
    problem = formula_problem(name)
    return f"{_quoted(name)} contains {problem}" if problem else None


def _n4(d, _ctx):
    name = d["name"]
    if not isinstance(name, str):
        return None
    _, colon, tail = name.partition(":")
    if _CLAIM_SEPARATOR.search(name) or (colon and len(tail.split()) > MAX_SUBTITLE_WORDS):
        return f"{_quoted(name)} is a 'Name: claim' sentence, not a noun phrase"
    return None


def _n5(d, _ctx):
    name = d["name"]
    if not isinstance(name, str):
        return None
    verbs = [w for w in _WORD.findall(name) if w.casefold() in CLAIM_VERBS]
    if verbs:
        return f"{_quoted(name)} states a claim ('{verbs[0]}')"
    return None


N1 = Rule("N1", FAIL, "concept name is a non-empty string", _n1)
N2 = Rule("N2", FAIL, f"concept name has at most {MAX_NAME_WORDS} words and "
                      f"{MAX_NAME_CHARS} characters", _n2)
N3 = Rule("N3", FAIL, "concept name contains no formula", _n3)
N4 = Rule("N4", FAIL, "concept name is a noun phrase, not 'Name: claim'", _n4)
N5 = Rule("N5", FAIL, "concept name states no claim", _n5)

NAME_RUBRIC = Rubric("concept_names", (N1, N2, N3, N4, N5))


def name_problems(name: Any) -> list[RuleResult]:
    """The rules one name breaks (empty when it passes)."""
    d = {"name": name}
    results = []
    for rule in NAME_RUBRIC.rules:
        message = rule.check(d, None)
        if message is not None:
            results.append(RuleResult(rule.id, rule.severity, message))
        if rule.id == "N1" and message is not None:
            break  # the other rules read a string that is not there
    return results


def check_names(names: Iterable[Any]) -> CheckReport:
    """One report over every name (a name appears once however often it is listed)."""
    results: list[RuleResult] = []
    seen: set[str] = set()
    for name in names:
        key = repr(name)
        if key in seen:
            continue
        seen.add(key)
        results.extend(name_problems(name))
    return CheckReport(NAME_RUBRIC.name, tuple(results))


def foundation_names(key_concepts: Any, prerequisite_map: Any) -> list[Any]:
    """Every name a foundation introduces: key concepts, then the map's keys and values."""
    names: list[Any] = list(key_concepts) if isinstance(key_concepts, list) else []
    if isinstance(prerequisite_map, dict):
        for source, prereqs in prerequisite_map.items():
            names.append(source)
            if isinstance(prereqs, list):
                names.extend(prereqs)
    return names


def correction_message(report: CheckReport, *, limit: int = 20) -> str:
    """The append-only correction turn: the failed rule ids and what was wrong."""
    failures = report.failures
    lines = [f"- {r.rule_id}: {r.message}" for r in failures[:limit]]
    if len(failures) > limit:
        lines.append(f"- … and {len(failures) - limit} more")
    return CONCEPT_NAME_CORRECTION.format(failures="\n".join(lines))


def summarize_check(report: CheckReport, attempt: int) -> str:
    """One-line AgentEvent detail for a name check (unique rule ids)."""
    unique = CheckReport(report.rubric, tuple({r.rule_id: r for r in report.results}.values()))
    return summarize(unique, attempt)


# ── Repair ───────────────────────────────────────────────────────────────────

def _cap_words(words: list[str]) -> list[str]:
    if len(words) <= MAX_NAME_WORDS:
        return words
    window = words[:MAX_NAME_WORDS]
    if words[MAX_NAME_WORDS].casefold() not in _STOPWORDS:
        # the next word continues the phrase: cut at the last phrase boundary inside it
        cuts = [i for i, w in enumerate(window) if i >= 2 and w.casefold() in _STOPWORDS]
        if cuts:
            window = window[:cuts[-1]]
    return window


def _strip_stopwords(words: list[str]) -> list[str]:
    while words and words[-1].casefold() in _STOPWORDS:
        words = words[:-1]
    return words


def repair_name(name: Any, *, fallback: str) -> str:
    """A short, formula-free noun phrase for a failing name; a passing name unchanged."""
    if not name_problems(name):
        return name
    if not isinstance(name, str):
        return fallback
    text = " ".join(name.split())
    segments = [s for s in _SEPARATOR.split(text) if s and _WORD.search(s)]
    text = segments[0] if segments else ""
    text = _APPLIED_TOKEN.sub(" ", text)  # "O(n log n) sorting" -> " sorting", not "O sorting"
    while _PARENTHETICAL.search(text):
        text = _PARENTHETICAL.sub("", text)
    words = text.split()
    for i, word in enumerate(words):
        if any(w.casefold() in CLAIM_VERBS for w in _WORD.findall(word)):
            words = words[:i]
            break
    text = _SPACED_OPERATOR.sub(r"\1", " ".join(words))
    words = [w.strip(",.;:()[]{}\"'") for w in text.split()]
    words = [w for w in words if w and _WORD.search(w) and formula_problem(w) is None]
    words = _strip_stopwords(_cap_words(words))
    text = " ".join(words)
    while len(text) > MAX_NAME_CHARS and len(words) > 1:
        words = _strip_stopwords(words[:-1]) or words[:1]
        text = " ".join(words)
    text = text[:MAX_NAME_CHARS].strip()
    return text if text and not name_problems(text) else fallback


@dataclass
class NameRepair:
    """A foundation's names after repair, and what changed."""

    key_concepts: list[str]
    prerequisite_map: dict[str, list[str]]
    renamed: dict[str, str] = field(default_factory=dict)  # original -> new, changed only
    report: CheckReport = field(default_factory=lambda: CheckReport(NAME_RUBRIC.name))
    changed: bool = False

    def summary(self, *, limit: int = 5) -> str:
        """WARN AgentEvent detail: the rules broken and input -> output examples."""
        ids = ",".join(dict.fromkeys(self.report.failed_ids)) or "shape"
        pairs = [f"{_quoted(old)} -> \"{new}\"" for old, new in self.renamed.items()]
        more = f"; … and {len(pairs) - limit} more" if len(pairs) > limit else ""
        return (f"WARN {ids}: {len(self.renamed)} concept name(s) repaired: "
                + "; ".join(pairs[:limit]) + more)


def _norm(name: str) -> str:
    return name.strip().casefold()


def repair_names(key_concepts: Any, prerequisite_map: Any) -> NameRepair:
    """Repair every name in a foundation consistently. Pure; returns new containers."""
    keys_in = list(key_concepts) if isinstance(key_concepts, list) else []
    map_in = prerequisite_map if isinstance(prerequisite_map, dict) else {}
    report = check_names(foundation_names(keys_in, map_in))

    taken: set[str] = set()      # normalized final names in use
    by_norm: dict[str, str] = {}  # normalized original string name -> final name
    renamed: dict[str, str] = {}

    def unique(base: str) -> str:
        if _norm(base) not in taken:
            return base
        n = 2
        while True:
            suffix = f" ({n})"
            candidate = base[:MAX_NAME_CHARS - len(suffix)].rstrip() + suffix
            if _norm(candidate) not in taken:
                return candidate
            n += 1

    # Passing key concepts keep their names and are reserved first, so a repaired name
    # never takes a name the model already used for a different concept.
    for name in keys_in:
        if isinstance(name, str) and not name_problems(name) and _norm(name) not in by_norm:
            by_norm[_norm(name)] = name
            taken.add(_norm(name))

    def assign(name: Any, fallback: str) -> str:
        if isinstance(name, str) and _norm(name) in by_norm:
            return by_norm[_norm(name)]
        final = unique(repair_name(name, fallback=fallback))
        taken.add(_norm(final))
        if isinstance(name, str):
            by_norm[_norm(name)] = final
        return final

    keys_out: list[str] = []
    for i, name in enumerate(keys_in, start=1):
        final = assign(name, f"Concept {i}")
        if final not in keys_out:
            keys_out.append(final)

    map_out: dict[str, list[str]] = {}
    extra = 0
    for source, prereqs in map_in.items():
        if not isinstance(source, str):
            continue
        extra += 1
        new_source = assign(source, f"Prerequisite {extra}")
        values = map_out.setdefault(new_source, [])
        for prereq in prereqs if isinstance(prereqs, list) else []:
            if not isinstance(prereq, str):
                continue
            extra += 1
            new_prereq = assign(prereq, f"Prerequisite {extra}")
            if new_prereq not in values:
                values.append(new_prereq)

    for name in foundation_names(keys_in, map_in):
        if isinstance(name, str) and name in renamed:
            continue
        if isinstance(name, str) and _norm(name) in by_norm and by_norm[_norm(name)] != name:
            renamed[name] = by_norm[_norm(name)]

    changed = keys_out != keys_in or map_out != map_in
    return NameRepair(keys_out, map_out, renamed, report, changed)
