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
            Hyphenated words ("1-D") pass, and so does " - " joining a name's first two
            words when both are single capitalised words and the right one ends the name or
            is followed by a lowercase word ("Gauss - Newton", "Gauss - Newton method");
            "Momentum - Faster Convergence" and "Learning Rate - Too High Diverges" fail.
  N5  FAIL  The name states no claim: a CLAIM_VERBS word (is, are, equals, ensures,
            causes, means, yields, prevents, must, should, ...) standing as a whole
            whitespace token with words on both sides, i.e. a clause ("Least-squares cost is
            convex", "Ridge yields a unique solution"), or an END_CLAIM_VERBS word (vanishes,
            diverges, decreases, ...) ending a name of two or more words ("Gradient
            vanishes"). Hyphenated tokens stay whole ("IS-LM model", "K-means"); "causes of"
            and "means" after a single letter ("k means") are nouns; a name whose FIRST word
            is a question word is a question, not a claim ("What is a monad"), but a
            relative clause is not ("Softmax, which is differentiable" fails). "Equal error
            rate", "Bond yields", "Causes of overfitting", "Means-end analysis" pass.

Repair (repair_name), for a failing name only — a passing name is returned untouched:
  1. read " - " between capitalised words as a hyphen; take the first ":" / ";" /
     spaced-dash segment that has a letter or digit (the head); if the head passes, use it;
  2. otherwise build a fragment: function-notation tokens become their function name when it
     is a word ("softmax(QK^T)" -> "softmax", "O(n log n)" -> "Big-O") and are dropped when
     it is one letter ("J(θ)=…"); parenthetical groups are dropped;
  3. cut at the first claim clause;
  4. glue spaced operators to their operands ("1 / L" -> "1/L"), then drop every token that
     holds a formula and every token with no letter or digit;
  5. cap to MAX_NAME_WORDS words, cutting at the last phrase boundary (a stopword) inside the
     window when the next word continues the phrase, drop trailing stopwords, cap characters;
  6. if the fragment is lossy (one word left of three or more, or fewer than half the head's
     words) and the head trimmed to the caps passes, use that instead;
  7. if nothing passes, use the caller's fallback ("Concept 3").
repair_names applies it across a foundation: every passing name (key concept or map-only)
keeps its name; a failing name whose repair equals a passing name (any case) merges into it;
two failing names that repair to the same text stay distinct (" (2)"); the map is rewritten
with the new names.
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

# Verbs only: words that double as nouns or adjectives (means, yields, causes, equal,
# ensures) name real concepts ("K-means", "Bond yields", "Equal error rate").
# A clause needs words on both sides of the verb, so the noun uses of ensures / causes /
# means / yields ("Bond yields", "Causes of overfitting") never qualify.
CLAIM_VERBS = frozenset({
    "is", "are", "was", "were", "equals", "implies", "guarantees", "converges", "diverges",
    "becomes", "ensures", "causes", "means", "yields", "prevents", "must", "should",
})
# Intransitive claims that end a short sentence ("Gradient vanishes").
END_CLAIM_VERBS = frozenset({
    "vanishes", "explodes", "diverges", "converges", "decreases", "increases", "saturates",
})
_INTERROGATIVES = frozenset({"what", "why", "how", "when", "where", "which", "who", "whether"})
_TOKEN_PUNCT = ",.;:!?()[]{}\"'"
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
# "Gauss - Newton", "Gauss - Newton method" — not Title Case "Momentum - Faster Convergence"
_SPACED_COMPOUND = re.compile(r"^([A-Z]\w*) - ([A-Z]\w*)(?=$|\s+[a-z])")
_FUNCTION_NAME = re.compile(r"^[^\W\d_]+(?=\()")


def _join_compounds(text: str) -> str:
    """Read " - " between two capitalised words as a hyphen ("Gauss - Newton")."""
    return _SPACED_COMPOUND.sub(r"\1-\2", text)


def _claim_index(words: list[str]) -> int | None:
    """Index of the first claim verb that forms a clause, or None."""
    bare = [w.strip(_TOKEN_PUNCT).casefold() for w in words]
    if not bare or bare[0] in _INTERROGATIVES:
        return None  # a question names a topic, it does not state the answer
    for i in range(1, len(bare) - 1):
        word = bare[i]
        if word not in CLAIM_VERBS:
            continue
        if word == "causes" and bare[i + 1] == "of":
            continue  # "Root causes of failure"
        if word == "means" and len(bare[i - 1]) == 1:
            continue  # "k means clustering"
        return i
    if len(bare) >= 2 and bare[-1] in END_CLAIM_VERBS:
        return len(bare) - 1
    return None


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
    if (_CLAIM_SEPARATOR.search(_join_compounds(name))
            or (colon and len(tail.split()) > MAX_SUBTITLE_WORDS)):
        return f"{_quoted(name)} is a 'Name: claim' sentence, not a noun phrase"
    return None


def _n5(d, _ctx):
    name = d["name"]
    if not isinstance(name, str):
        return None
    words = name.split()
    i = _claim_index(words)
    if i is not None:
        return f"{_quoted(name)} states a claim ('{words[i].strip(_TOKEN_PUNCT)}')"
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


def _function_head(match: re.Match) -> str:
    """A function-notation token reduced to its function name, when that is a word."""
    head = _FUNCTION_NAME.match(match.group(0))
    name = head.group(0) if head else ""
    if name == "O":
        return " Big-O "  # asymptotic notation: "O(n log n) sorting" -> "Big-O sorting"
    return f" {name} " if len(name) >= 2 else " "  # J(θ)=…, f(x): a symbol, not a name


def _cap_text(words: list[str]) -> str:
    words = _strip_stopwords(_cap_words(words))
    text = " ".join(words)
    while len(text) > MAX_NAME_CHARS and len(words) > 1:
        words = _strip_stopwords(words[:-1]) or words[:1]
        text = " ".join(words)
    return text[:MAX_NAME_CHARS].strip()


def _fragment(head: str) -> str:
    text = _APPLIED_TOKEN.sub(_function_head, head)
    while _PARENTHETICAL.search(text):
        text = _PARENTHETICAL.sub("", text)
    words = text.split()
    cut = _claim_index(words)
    if cut is not None:
        words = words[:cut]
    text = _SPACED_OPERATOR.sub(r"\1", " ".join(words))
    words = [w.strip(_TOKEN_PUNCT) for w in text.split()]
    words = [w for w in words if w and _WORD.search(w) and formula_problem(w) is None]
    return _cap_text(words)


def _lossy(fragment: str, head: str) -> bool:
    kept, total = len(fragment.split()), len(head.split())
    return (kept == 1 and total >= 3) or kept * 2 < total


def repair_name(name: Any, *, fallback: str) -> str:
    """A short, formula-free noun phrase for a failing name; a passing name unchanged."""
    if not name_problems(name):
        return name
    if not isinstance(name, str):
        return fallback
    text = _join_compounds(" ".join(name.split()))
    segments = [s for s in _SEPARATOR.split(text) if s and _WORD.search(s)]
    head = segments[0].strip() if segments else ""
    if head and not name_problems(head):
        return head  # "Learning rate: step size α" -> "Learning rate"
    fragment = _fragment(head)
    if fragment and _lossy(fragment, head):
        trimmed = _cap_text(head.split())
        if trimmed and not name_problems(trimmed):
            return trimmed
    return fragment if fragment and not name_problems(fragment) else fallback


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

    # Every passing name — key concept or map-only — keeps its name and is reserved first.
    passing: dict[str, str] = {}  # normalized passing name -> its (first) spelling
    for name in foundation_names(keys_in, map_in):
        if isinstance(name, str) and not name_problems(name):
            passing.setdefault(_norm(name), name)
    taken: set[str] = set(passing)  # normalized final names in use
    by_norm: dict[str, str] = dict(passing)  # normalized original string name -> final name
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

    def assign(name: Any, fallback: str) -> str:
        if isinstance(name, str) and _norm(name) in by_norm:
            return by_norm[_norm(name)]
        repaired = repair_name(name, fallback=fallback)
        if repaired != fallback and _norm(repaired) in passing:
            # "Learning rate: step size α" next to a passing "Learning rate": the same
            # concept, so merge — a suffixed copy would strip the real one of its edges.
            final = passing[_norm(repaired)]
        else:
            final = unique(repaired)  # two failing names repaired alike stay distinct
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
            if new_prereq != new_source and new_prereq not in values:  # no merged self-loop
                values.append(new_prereq)

    for name in foundation_names(keys_in, map_in):
        if isinstance(name, str) and name in renamed:
            continue
        if isinstance(name, str) and _norm(name) in by_norm and by_norm[_norm(name)] != name:
            renamed[name] = by_norm[_norm(name)]

    changed = keys_out != keys_in or map_out != map_in
    return NameRepair(keys_out, map_out, renamed, report, changed)
