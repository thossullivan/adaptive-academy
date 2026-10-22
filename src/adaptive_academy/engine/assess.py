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
# Rubric must_include / weak_signs (and a source anchor's key_points) are checked against the
# learner's text. No word matcher strict enough to stop wrong answers leaves correct ones alone,
# so the checks are only CONFIDENT about absence and leave everything uncertain to the grader:
#   - a WORD must_include item is satisfied when its words occur un-negated in one sentence;
#     a HARD gap (capped by penalize_score) only when none of its content words occur anywhere;
#     otherwise "possibly missing", a note the grader decides by meaning (build_grade_prompt).
#   - a WORD weak sign is a HARD misconception only as a full, un-negated phrase; a negated or
#     partial match is a "possible misconception" note for the grader.
#   - a FORMULA item (is_formula_like) is never a hard gap: a correct answer may use other
#     variable names (w for θ) or another convention (MSE without ½), so the grader judges it.
# Words are compared casefolded, accents and markdown emphasis stripped, possessives dropped,
# contractions expanded, inflected ("residuals", "converged"), and as compounds either way
# ("pre-training" ~ "pretraining" ~ "pre training"); digits and code tokens compare exactly
# ("L2" is not "L1", "np.dot" is not "dot"). Formula items are compared on an ASCII form
# (normalize_math), so X^T matches Xᵀ.

# Unicode math notation -> ASCII. Spaced where the ASCII is a word ("grad J" for ∇J).
_MATH_CHARS = {
    "−": "-", "∓": "-+", "±": "+-", "‖": "||", "∥": "||", "∣": "|", "×": "*", "·": "*",
    "⋅": "*", "∗": "*", "÷": "/", "∕": "/", "⁄": "/", "√": " sqrt ", "∇": " grad ",
    "∂": " d ", "∑": " sum ", "∏": " prod ", "∫": " int ", "≤": "<=", "⩽": "<=", "≥": ">=",
    "⩾": ">=", "≠": "!=", "≈": "~", "∼": "~", "≃": "~", "∝": "~", "≡": "=", "≔": ":=",
    "→": "->", "⟶": "->", "←": "<-", "⇒": "=>", "∞": " inf ", "∈": " in ", "⊤": "^T",
    "ᵀ": "^T", "′": "'", "″": "''", "⟨": "<", "⟩": ">",
}


def _chars(*codepoints: int) -> str:
    return "".join(map(chr, codepoints))


# Prose typography -> ASCII (hyphens/dashes, curly quotes, odd spaces, ellipsis, zero-width
# space). Not notation: an en dash in "Gauss–Newton" is not a minus sign.
_TEXT_CHARS = {
    **dict.fromkeys(_chars(0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015), "-"),
    **dict.fromkeys(_chars(0x2018, 0x2019, 0x201A, 0x201B), "'"),
    **dict.fromkeys(_chars(0x201C, 0x201D, 0x201E, 0x201F), '"'),
    **dict.fromkeys(_chars(0x00A0, 0x2007, 0x2009, 0x200A, 0x202F), " "),
    chr(0x2026): "...", chr(0x200B): "",
}
# Greek symbol variants and the micro sign are always notation (never Greek prose).
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
_STOPWORDS = frozenset({
    "a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "via", "with", "and", "or",
    "is", "are", "be", "it", "its", "as", "from", "that", "this", "into", "onto", "than",
})
_NEGATIONS = frozenset({"not", "no", "never", "without", "neither", "nor"})
_NOT_NEGATING = frozenset({"only", "just", "merely", "simply"})  # "not only X" asserts X
# Scripts written without spaces between words (kana, CJK ideographs): each character is its
# own token.
_CJK = "{}-{}{}-{}{}-{}".format(*_chars(0x3040, 0x30FF, 0x3400, 0x4DBF, 0x4E00, 0x9FFF))
# A word token: Unicode word characters, with dotted/slashed parts (np.dot, TCP/IP) and a
# C++ / C# / A* suffix kept on, so code tokens compare whole.
_TOKEN = re.compile(r"\w+(?:[./]\w+)*(?:\+\+|[#*](?!\w))?")
_CLAUSE_BREAK = re.compile(r"[,.;:!?()\[\]。！？；，、]")
_SENTENCE_BREAK = re.compile(r"[.;!?。！？；]|\n\s*\n")
_COMPOUND_GAP = re.compile(r"\s*-?\s*")  # what may sit inside a compound: pre training, 1-D
# Markdown emphasis, paired so A*, C# and x * y keep their stars: **bold**, *it*, ***both***,
# and _two words_ (a single-word _x_ is left alone: __init__ is a name, and a token's
# underscore parts match anyway). Code-span backticks become spaces.
_EMPHASIS = (
    re.compile(r"(?<![\w*])(\*{1,3})(?=[^\s*])([^\n]+?)(?<=[^\s*])\1(?![\w*])"),
    re.compile(r"(?<![\w_])(_{1,3})(?=[^\s_])([^\n]*?\s[^\n]*?)(?<=[^\s_])\1(?![\w_])"),
)
# Contractions spelled out (can't -> can not, not "ca not") and possessives dropped
# (Jensen's -> Jensen, Bayes' -> Bayes), on casefolded text with ASCII apostrophes.
_CONTRACTIONS = tuple((re.compile(p), r) for p, r in (
    (r"\bcan't\b", "can not"), (r"\bwon't\b", "will not"), (r"\bshan't\b", "shall not"),
    (r"\bain't\b", "is not"), (r"n't\b", " not"), (r"\bcannot\b", "can not"),
    (r"'re\b", " are"), (r"'ve\b", " have"), (r"'ll\b", " will"), (r"'m\b", " am"),
    (r"'d\b", " would"), (r"(?<=\w)'s\b", ""), (r"(?<=s)'(?!\w)", ""),
))


@lru_cache(maxsize=4096)
def _char_ascii(c: str) -> tuple[str, bool]:
    """One character's ASCII form (for formula matching), and whether it is math notation.
    A plain Greek letter maps to its name but is not flagged here: is_formula_like tells
    Greek notation (θ in "Xθ") from Greek prose itself."""
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
            return f" {rest[0].lower()} ", False
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
    """Lower-cased ASCII form of text with Unicode math in it, for formula items: Xᵀ -> x^t,
    θ -> theta, ½ -> 1/2, ‖ -> ||, − -> -, x² -> x^2, x₁ -> x_1. Whitespace is left as is."""
    return _ascii(s).lower()


def _formula_key(s: str) -> str:
    return "".join(normalize_math(s).split())


def _is_greek(c: str) -> bool:
    return unicodedata.name(c, "").startswith("GREEK")


def _greek_notation(item: str) -> bool:
    """Greek used as notation: a token mixing Greek with Latin letters or digits ("Xθ"), or
    a lone Greek letter in an item with no Greek word of 2+ letters ("learning rate η";
    in "η κλίση" the η is the Greek article)."""
    greek = [t for t in re.findall(r"\w+", item) if any(_is_greek(c) for c in t)]
    if any(not all(_is_greek(c) for c in t) for t in greek):
        return True
    return any(len(t) == 1 for t in greek) and not any(len(t) >= 2 for t in greek)


_SYMBOL_ACRONYM = re.compile(r"(?<![\w*+#])[A-Z][A-Z0-9]*(?:\+\+|[#*])(?![\w*+#])")  # C++ A*
_CAPS_ACRONYM = re.compile(r"(?<!\w)[A-Z][A-Z0-9]{1,5}(?!\w)")  # KL, L2, MSE, GPT
_SLASH_WORDS = re.compile(r"(?<![\w/])[A-Za-z]{2,}(?:/[A-Za-z]{2,})+(?![\w/])")  # TCP/IP
_DOTTED_OR_SNAKE = re.compile(r"(?<![\w.])[\w.]*[._][\w.]*(?!\w)")
# A Leibniz derivative (dL/dw, dy/dx, dz/dx1): notation, though it looks like word/word.
_LEIBNIZ = re.compile(r"(?<![\w/])d[A-Za-z]\d*/d[A-Za-z]\d*(?![\w/])")


def _is_identifier(tok: str) -> bool:
    """snake_case, __dunder__ or dotted code names (log_softmax, np.dot), told from math
    subscripts (d_k, x_i, X.T) by having a part of 2+ letters."""
    if tok.startswith(".") or tok.endswith("."):
        return False
    return any(len(p) >= 2 and p.isalpha() for p in re.split(r"[._]+", tok))


def _mask_word_tokens(item: str) -> str:
    """The item with its acronyms and code identifiers replaced by a plain word, so their
    symbols (the ++ in C++, the _ in log_softmax) don't read as notation. Unpadded: spaces
    around the word would make the hyphen in AUC-ROC a spaced minus."""
    s = _SYMBOL_ACRONYM.sub("wordtoken", item)
    s = _SLASH_WORDS.sub("wordtoken", s)
    s = _DOTTED_OR_SNAKE.sub(
        lambda m: "wordtoken" if _is_identifier(m.group()) else m.group(), s)
    return _CAPS_ACRONYM.sub("wordtoken", s)


def is_formula_like(item: str) -> bool:
    """Whether a rubric item is notation (checked by the grader) rather than words (checked
    here). Acronyms (KL, L2, MSE, C++, A*, TCP/IP, AUC-ROC), word/word ("and/or") and code
    identifiers (log_softmax, __init__, np.dot) count as words, not notation. Otherwise
    formula-like when the item has ANY notation in it:
      - a Unicode math character (superscript/subscript, ∇ ‖ − ½ ...) or Greek used as
        notation (_greek_notation; Greek-language prose is words),
      - an ASCII operator or bracket: ^ _ = + * / \\ | < > ~ { } [ ],
      - a function call shape, a letter or digit directly before "(" ("f(x)", "sqrt(d)"),
      - a minus between single symbols ("x - y", "x-y") or a spaced minus; a hyphenated
        word ("p-value", "k-means", "top-1", "GPT-3") is not one,
      - a Leibniz derivative ("dL/dw", "dy/dx"),
    or when it has no natural-language word at all: no word of 3+ letters in any script
    (other than a Greek letter name or a function name like sqrt/log/max) and no CJK
    character, e.g. "x theta", "X.T"."""
    if any(_char_ascii(c)[1] for c in item) or _greek_notation(item) or _LEIBNIZ.search(item):
        return True
    masked = _mask_word_tokens(item)
    norm = normalize_math(masked)
    if re.search(r"[\^_=+*/\\|<>~{}\[\]]", norm):
        return True
    if re.search(r"[a-z0-9]\(", norm):
        return True
    if re.search(r"\b[a-z0-9]\s*-\s*[a-z0-9]\b", norm) or re.search(r"\s-\s", norm):
        return True
    words = re.findall(r"[^\W\d_]+", masked.casefold())
    return not any((len(w) >= 3 and w not in _MATH_WORDS) or re.search(f"[{_CJK}]", w)
                   for w in words)


def _strip_emphasis(s: str) -> str:
    for _ in range(3):  # nested: **bold _two words_ bold**
        before = s
        for pattern in _EMPHASIS:
            s = pattern.sub(r"\2", s)
        if s == before:
            break
    return re.sub(r"\*{2,}", " ", s.replace("`", " "))


def _word_text(s: str) -> str:
    """Text prepared for word matching, in any script: typography to ASCII, NFKC, casefold,
    accents and markdown emphasis stripped, contractions spelled out, possessives dropped,
    CJK characters spaced apart."""
    s = "".join(_TEXT_CHARS.get(c, c) for c in s)
    s = unicodedata.normalize("NFKC", s).casefold()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = _strip_emphasis(unicodedata.normalize("NFC", s))
    for pattern, repl in _CONTRACTIONS:
        s = pattern.sub(repl, s)
    return re.sub(f"([{_CJK}])", r" \1 ", s)


@lru_cache(maxsize=4096)
def _inflections(w: str) -> frozenset[str]:
    forms = {w + "s", w + "es", w + "ed", w + "ing"}
    if w.endswith("e"):
        forms |= {w + "d", w[:-1] + "ing"}
    if w.endswith("y"):
        forms |= {w[:-1] + "ies", w[:-1] + "ied"}
    if w[-1] not in "aeiouwxy" and w[-2] in "aeiou" and w[-3] not in "aeiou":
        forms |= {w + w[-1] + "ed", w + w[-1] + "ing"}  # overfit -> overfitting
    return frozenset(forms)


@lru_cache(maxsize=16384)
def _bases(w: str) -> frozenset[str]:
    """The word and the bases (3+ letters) it inflects: converged -> converge, pretraining ->
    pretrain, overfitting -> overfit. Two words match when their bases meet, so inflected
    forms match each other (converged ~ converges). Digits, short words, acronyms with
    symbols and code names are their own only base: L2 != L1, np.dot != dot."""
    if len(w) < 3 or not w.isalpha():
        return frozenset({w})
    out = {w}
    for cut in (1, 2, 3, 4):
        stem = w[:-cut]
        out |= {b for b in (stem, stem + "e", stem + "y") if len(b) >= 3 and w in _inflections(b)}
    return frozenset(out)


def _index(forms) -> frozenset[str]:
    return frozenset(b for f in forms for b in _bases(f))


def _matches(w: str, index: frozenset[str]) -> bool:
    return not _bases(w).isdisjoint(index)


@dataclass(frozen=True)
class _Pos:
    """One word of the learner's text: the bases of the forms it can match (a code token also
    matches its parts: np.dot -> np, dot), the bases of it written together with the next
    word ("pre training" -> pretraining, "1-D" -> 1d), its sentence, and whether a negation
    directly precedes it in the same clause, stopwords aside ("is not a convex function")."""

    index: frozenset[str]
    joined: frozenset[str]
    sentence: int
    negated: bool


@dataclass(frozen=True)
class _Answer:
    positions: list[_Pos]
    # Per sentence, the bases of every word and of the un-negated words (joins included).
    sentences: list[tuple[frozenset[str], frozenset[str]]]
    everywhere: frozenset[str]


def _code_parts(tok: str) -> list[str]:
    dotted = re.split(r"[./]", tok)
    return [p for p in {*dotted, *(p for d in dotted for p in d.split("_"))} if p and p != tok]


def _read_answer(text: str) -> _Answer:
    s = _word_text(text)
    matches = list(_TOKEN.finditer(s))
    gaps = [s[(matches[k - 1].end() if k else 0):m.start()] for k, m in enumerate(matches)]
    toks = [m.group() for m in matches]
    positions: list[_Pos] = []
    sentence, prev = 0, ""  # prev: the clause's last word that isn't a stopword
    for k, tok in enumerate(toks):
        if k and _SENTENCE_BREAK.search(gaps[k]):
            sentence += 1
        if k and _CLAUSE_BREAK.search(gaps[k]):
            prev = ""
        negated = prev in _NEGATIONS and tok not in _NOT_NEGATING
        if tok not in _STOPWORDS:
            prev = tok
        compound = k + 1 < len(toks) and _COMPOUND_GAP.fullmatch(gaps[k + 1]) is not None
        positions.append(_Pos(
            index=_index([tok, *_code_parts(tok)]),
            joined=_index([tok + toks[k + 1]]) if compound else frozenset(),
            sentence=sentence, negated=negated))
    sentences: list[tuple[frozenset[str], frozenset[str]]] = []
    for n in range(sentence + 1 if positions else 0):
        here = [p for p in positions if p.sentence == n]
        sentences.append((
            frozenset().union(*(p.index | p.joined for p in here)),
            frozenset().union(*(p.index | p.joined for p in here if not p.negated))))
    everywhere = frozenset().union(*(p.index | p.joined for p in positions))
    return _Answer(positions, sentences, everywhere)


def _item_tokens(item: str) -> list[str]:
    return _TOKEN.findall(_word_text(item))


def _covered(tokens: list[str], index: frozenset[str]) -> bool:
    """Every content word of the item (stopwords may be skipped) is in `index`, alone or
    written together with the next item word ("data set" ~ dataset)."""
    content = [t for t in tokens if t not in _STOPWORDS]
    skippable = _STOPWORDS if content else frozenset()
    n = len(tokens)

    @lru_cache(maxsize=None)
    def from_(i: int) -> bool:
        if i >= n:
            return True
        if tokens[i] in skippable and from_(i + 1):
            return True
        if _matches(tokens[i], index) and from_(i + 1):
            return True
        return i + 1 < n and _matches(tokens[i] + tokens[i + 1], index) and from_(i + 2)

    return from_(0)


def _states_negation(tokens: list[str]) -> bool:
    """An item that states a negation itself ("no closed-form solution") is matched with
    it, so negated words in the answer count for it."""
    return any(t in _NEGATIONS for t in tokens)


def _in_one_sentence(tokens: list[str], answer: _Answer, *, respect_negation: bool) -> bool:
    return any(_covered(tokens, unnegated if respect_negation else every)
               for every, unnegated in answer.sentences)


def _any_word_present(tokens: list[str], answer: _Answer) -> bool:
    """Whether ANY content word of the item occurs anywhere in the answer, negated or not: as
    a stem, an exact digit/acronym/code token or one of a code token's parts (np.dot -> dot),
    or as a compound either way (data set ~ dataset, pretraining ~ pre-training)."""
    content = [t for t in tokens if t not in _STOPWORDS and t not in _NEGATIONS] or tokens
    candidates = [*content, *(p for t in content for p in _code_parts(t) if len(p) >= 2),
                  *(a + b for a, b in zip(tokens, tokens[1:]))]
    return any(_matches(c, answer.everywhere) for c in candidates)


def _phrase_matches(tokens: list[str], answer: _Answer) -> list[bool]:
    """Every place the item occurs as its words in order, contiguous and in one sentence
    (inflections and compounds either way allowed, so "always converge" is in "always
    converges" and "overfit" in "over-fits", but "memory" is not in "memoryless"); for each,
    whether a negation directly precedes it ("does not always converge")."""
    ps, n = answer.positions, len(tokens)

    def from_(i: int, j: int, sentence: int) -> bool:
        if i == n:
            return True
        if j >= len(ps) or ps[j].sentence != sentence:
            return False
        if _matches(tokens[i], ps[j].index) and from_(i + 1, j + 1, sentence):
            return True
        if (i + 1 < n and _matches(tokens[i] + tokens[i + 1], ps[j].index)
                and from_(i + 2, j + 1, sentence)):
            return True
        return _matches(tokens[i], ps[j].joined) and from_(i + 1, j + 2, sentence)

    return [p.negated for j, p in enumerate(ps) if n and from_(0, j, p.sentence)]


@dataclass
class RulesCheck:
    """The deterministic anchor checks on one response. Only `gaps` caps the score; every
    other list is a note for the grader, who decides by meaning (build_grade_prompt)."""

    gaps: list[str] = field(default_factory=list)  # hard: they set the score ceilings
    # Every formula-like must_include item: the grader is told to judge each by meaning.
    formulas: list[str] = field(default_factory=list)
    # Formula-like must_include items the text doesn't contain literally.
    formulas_unmatched: list[str] = field(default_factory=list)
    # Word must_include items neither found nor confidently absent: a near miss (L1 for L2),
    # a negated mention, or words spread over sentences.
    possibly_missing: list[str] = field(default_factory=list)
    # Word weak signs matched only negated or in part, and formula-like weak signs found
    # literally (a fragment can sit inside a correct expression).
    possible_misconceptions: list[str] = field(default_factory=list)

    @property
    def left_to_grader(self) -> list[str]:
        return self.formulas_unmatched + self.possibly_missing + self.possible_misconceptions


def check_anchor_terms(response: str, must_include: list[str],
                       weak_signs: list[str]) -> RulesCheck:
    """Deterministic anchor checks (§2.3): the LLM grader cannot paper over the hard ones.
    A word must_include item is satisfied when its words occur un-negated in one sentence, a
    hard gap only when none of its content words occur anywhere, and possibly missing
    otherwise. A word weak sign is a hard misconception only as a full, un-negated phrase,
    and a possible one when matched negated or when its words share a sentence. Formula-like
    items (is_formula_like) are always notes for the grader."""
    answer = _read_answer(response or "")
    text_formula = _formula_key(response or "")
    result = RulesCheck()
    for term in must_include:
        if not term or not term.strip():
            continue
        if is_formula_like(term):
            result.formulas.append(term)
            if _formula_key(term) not in text_formula:
                result.formulas_unmatched.append(term)
            continue
        tokens = _item_tokens(term)
        if not tokens or _in_one_sentence(
                tokens, answer, respect_negation=not _states_negation(tokens)):
            continue
        if _any_word_present(tokens, answer):
            result.possibly_missing.append(term)
        else:
            result.gaps.append(f"omitted required element: {term}")
    for sign in weak_signs:
        if not sign or not sign.strip():
            continue
        if is_formula_like(sign):
            if _formula_key(sign) in text_formula:
                result.possible_misconceptions.append(sign)
            continue
        tokens = _item_tokens(sign)
        found = _phrase_matches(tokens, answer)
        if found and (_states_negation(tokens) or not all(found)):
            result.gaps.append(f"contains likely misconception: {sign}")
        elif found or (tokens and _in_one_sentence(tokens, answer, respect_negation=False)):
            result.possible_misconceptions.append(sign)
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
                       possibly_missing: list[str] | None = None,
                       possible_misconceptions: list[str] | None = None) -> tuple[str, str]:
    """The notes the rules checks leave to the grader (check_anchor_terms): `formulas`, every
    formula-like must_include item; `possibly_missing`, word items the checks could neither
    find nor rule out; `possible_misconceptions`, weak signs matched only negated or in part,
    or written as notation. GRADE says how to judge each and what it costs."""
    lines = [f"CONCEPT: {concept_name}", f"PROBE KIND: {kind}", "", "RUBRIC / ANCHOR:"]
    for c in criteria:
        lines.append(f"- {c}")
    for heading, notes in (("EXPECTED FORMULAS:", formulas),
                           ("POSSIBLY MISSING:", possibly_missing),
                           ("POSSIBLE MISCONCEPTIONS:", possible_misconceptions)):
        if notes:
            lines.append(heading)
            lines += [f"- {n}" for n in notes]
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
             f"{len(rules.left_to_grader)} item(s) left to the grader: "
             + "; ".join(rules.left_to_grader))
    emit("prompt", GRADE.tag)
    system, user = build_grade_prompt(
        concept.name, kind, criteria, reference, response, formulas=rules.formulas,
        possibly_missing=rules.possibly_missing,
        possible_misconceptions=rules.possible_misconceptions)
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
