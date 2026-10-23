"""The demo topic: one example topic shaped like about three weeks of real use.

Built entirely in code, with no LLM call and no API key, so someone without a key can explore
every page with meaningful content in one click (`POST /api/demo`, `just seed`). The rows are
the same shape the real agents write: a researched foundation and reading list, a phased track
from the curriculum, a prerequisite graph, and a history of `Assessment` rows (the spine) with
the `AgentEvent` trace each engine would have emitted. Dates are relative to "now" so the
decay, retention and momentum views look alive whenever it is created.

The topic is flagged `is_demo` and titled "(demo)"; `remove_demo` deletes it and every row
that belongs to it by walking the foreign-key graph down from the topic.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import Table, delete, update
from sqlalchemy import select as sa_select
from sqlmodel import Session, SQLModel, col, select

from adaptive_academy.engine import graph
from adaptive_academy.engine.assess import GRADING_KINDS, level_from_score
from adaptive_academy.engine.attempt import ACCEPTED, OUTCOME_DETAILS, SUBMITTED_DETAIL
from adaptive_academy.engine.curriculum import load_bearing_concepts
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.memory import (
    index_assessment,
    index_message,
    index_question,
    index_text,
)
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Attempt,
    Concept,
    ConceptEdge,
    ConceptNote,
    Conversation,
    Deliverable,
    Item,
    KnowledgeEstimate,
    Message,
    Phase,
    RecallPrompt,
    ReferenceAnchor,
    Rubric,
    Sidebar,
    SourceDoc,
    SRSCard,
    Topic,
    TopicFoundation,
    TopicIntent,
    Track,
)
from adaptive_academy.prompts import (
    ANCHOR,
    ASSESS_ARTIFACT,
    CURRICULUM,
    DECAY_RECALL,
    PF_CONSOLIDATE,
    PF_GENERATE,
    REMEDIATE,
    RESEARCH_FOUNDATION,
    RETENTION,
    RUBRIC,
    TEACH,
    TUTOR_ATTEMPT_ACCEPTED,
    TUTOR_BASE,
    TUTOR_SOLUTION_GUARD,
    grade_prompt,
)

DEMO_TITLE = "Build LLMs from scratch (demo)"

# Serializes create/remove within the (single) API process, so two clicks can't build two demos.
_LOCK = threading.Lock()

# --- content --------------------------------------------------------------------------------

INTENT = {
    "goal": "Train a small GPT-style model end to end and be able to explain every component "
            "without notes.",
    "prior_knowledge": "Comfortable with Python and NumPy; calculus is rusty; have used "
                       "PyTorch but never built a model from scratch.",
    "time_budget": "6–8 hours a week",
}

OVERVIEW = (
    "A language model is a next-token predictor trained by gradient descent, so the path runs "
    "from automatic differentiation, through how text becomes vectors, to attention (the one "
    "genuinely new mechanism), and then to assembling and training the full Transformer. Each "
    "stage is built by hand before reading a reference implementation."
)

# Short keys for the concepts below.
CONCEPTS: dict[str, str] = {
    "chain": "Chain Rule and Computational Graphs",
    "backprop": "Backpropagation and Autograd",
    "bpe": "Byte-Pair Encoding Tokenization",
    "embed": "Token Embeddings",
    "lm": "Next-Token Prediction and Cross-Entropy",
    "attn": "Scaled Dot-Product Attention",
    "causal": "Causal Self-Attention",
    "mha": "Multi-Head Attention",
    "pos": "Positional Encodings",
    "resid": "Residual Connections and LayerNorm",
    "block": "Transformer Block",
    "adamw": "AdamW and Learning-Rate Warmup",
    "train": "Training Loop and Validation Loss",
    "sample": "Sampling: Temperature and Top-k",
    "kv": "KV Cache",
}

# The foundation's prerequisite map: concept -> the concepts it requires.
PREREQUISITES: dict[str, list[str]] = {
    "backprop": ["chain"],
    "embed": ["bpe"],
    "lm": ["backprop", "embed"],
    "attn": ["embed"],
    "causal": ["attn"],
    "mha": ["causal"],
    "pos": ["embed"],
    "resid": ["backprop"],
    "block": ["mha", "resid"],
    "adamw": ["backprop"],
    "train": ["lm", "block"],
    "sample": ["lm"],
    "kv": ["causal"],
}

# (title, url, tier, angle, summary, why, status)
SOURCES = [
    ("Attention Is All You Need", "https://arxiv.org/abs/1706.03762", 1,
     "foundational papers",
     "Introduces the Transformer: scaled dot-product attention, multi-head attention, "
     "sinusoidal positional encodings and the encoder-decoder stack.",
     "The primary source for the attention mechanism you will derive in Phase 3.",
     "accepted"),
    ("Neural Machine Translation of Rare Words with Subword Units",
     "https://arxiv.org/abs/1508.07909", 1, "tokenization",
     "Adapts byte-pair encoding to build a subword vocabulary by repeatedly merging the most "
     "frequent adjacent symbol pair.",
     "The original BPE-for-NLP paper; short enough to reimplement from the pseudocode.",
     "accepted"),
    ("Language Models are Unsupervised Multitask Learners",
     "https://cdn.openai.com/better-language-models/language_models_are_unsupervised_"
     "multitask_learners.pdf", 1, "foundational papers",
     "The GPT-2 report: a decoder-only Transformer trained on next-token prediction, with "
     "byte-level BPE and pre-LayerNorm blocks.",
     "The closest published design to the model you will train in Phase 4.",
     "accepted"),
    ("Autograd mechanics", "https://pytorch.org/docs/stable/notes/autograd.html", 2,
     "implementation",
     "How a framework records the computational graph and runs the backward pass, including "
     "gradient accumulation and in-place pitfalls.",
     "Read after your own autograd works, to compare design decisions.",
     "accepted"),
    ("Layer Normalization", "https://arxiv.org/abs/1607.06450", 2, "architecture details",
     "Normalizes across features within each example, so it works for any batch size and in "
     "recurrent and attention models.",
     "Explains the LayerNorm in every Transformer block.",
     "accepted"),
    ("Decoupled Weight Decay Regularization", "https://arxiv.org/abs/1711.05101", 2,
     "training",
     "Shows that L2 regularization and weight decay differ under Adam, and proposes AdamW.",
     "The optimizer you will use; the paper explains why the decay is decoupled.",
     "accepted"),
    ("RoFormer: Enhanced Transformer with Rotary Position Embedding",
     "https://arxiv.org/abs/2104.09864", 2, "architecture details",
     "Encodes position by rotating query and key vectors, so attention scores depend on "
     "relative position.",
     "A modern alternative to sinusoidal encodings, for the Phase 3 comparison.",
     "accepted"),
    ("Dive into Deep Learning: Attention Mechanisms and Transformers",
     "https://d2l.ai/chapter_attention-mechanisms-and-transformers/index.html", 3, "textbooks",
     "An open textbook chapter that builds attention up from kernel regression, with runnable "
     "code.",
     "A gentler second explanation when the paper is too terse.",
     "accepted"),
    ("Efficient Transformers: A Survey", "https://arxiv.org/abs/2009.06732", 3, "surveys",
     "Catalogues sparse, low-rank and kernel-based attention variants.",
     "Broad; useful after the basics, not before.",
     "pruned"),
]

# (title, est_hours, flags, items, deliverable)
# item: (type, text, concept keys, status, source index or None)
PHASES = [
    ("Phase 1: Autograd from first principles", "12–15 hours", [], [
        ("read", "Re-derive the chain rule for a two-layer MLP on paper before touching code.",
         ["chain"], "done", None),
        ("build", "Implement a scalar `Value` class with `+`, `*`, `tanh` and `backward()`; "
                  "check every gradient against finite differences.",
         ["backprop"], "done", None),
        ("read", "Compare your design with a framework's autograd notes, but only after your own "
                 "version passes its gradient checks.",
         ["backprop"], "done", 3),
        ("write", "Explain in your own words why gradients accumulate (`+=`) instead of being "
                  "overwritten in `backward()`.",
         ["backprop", "chain"], "done", None),
    ], ("blog", "Blog post: a 100-line autograd engine, and what the gradient checks caught.",
        ["Derives the backward rule for every op it implements",
         "Shows at least one gradient check failing, then passing",
         "Trains a small MLP on a toy dataset"])),
    ("Phase 2: Tokens and embeddings", "10–12 hours", [], [
        ("read", "Read the subword-units paper and write out the BPE merge loop as pseudocode.",
         ["bpe"], "done", 1),
        ("build", "Train a byte-level BPE tokenizer on a small public-domain corpus; compare its "
                  "compression with a reference tokenizer.",
         ["bpe"], "done", None),
        ("build", "Implement an embedding table and a bigram language model trained with "
                  "cross-entropy.",
         ["embed", "lm"], "done", None),
        ("write", "Spaced revisit: explain how gradients flow back through an embedding lookup.",
         ["backprop", "embed"], "done", None),
    ], ("repo", "A tokenizer repository with tests: lossless round-trip on arbitrary bytes.",
        ["Encode/decode round-trips any byte string",
         "Merges are learned, not hard-coded",
         "README reports compression on a held-out text"])),
    ("Phase 3: Attention: derive, implement, ablate", "15–18 hours", [], [
        ("read", "Derive why attention logits are scaled by 1/√d_k (§3.2 of the Transformer "
                 "paper).",
         ["attn"], "done", 0),
        ("build", "Implement single-head scaled dot-product attention in NumPy and check it "
                  "against a reference implementation on random inputs.",
         ["attn"], "done", None),
        ("build", "Add the causal mask and unit-test that position t never attends to t+1.",
         ["causal"], "doing", None),
        ("build", "Split attention into heads; ablate the head count (1, 2, 4, 8) on a tiny "
                  "character-level model.",
         ["mha"], "todo", None),
        ("read", "Compare sinusoidal and rotary positional encodings: what does each do to "
                 "relative position?",
         ["pos"], "todo", 6),
    ], ("ablation", "Ablation write-up: head count vs. validation loss on a character-level "
                    "model.",
        ["Same compute budget for every run",
         "Plots validation loss, not just training loss",
         "States what the result does and does not show"])),
    ("Phase 4: Train a tiny GPT", "20–25 hours", [], [
        ("build", "Assemble the Transformer block (pre-LayerNorm, residual stream, MLP) and stack "
                  "four of them.",
         ["block", "resid"], "todo", 4),
        ("build", "Write the training loop with AdamW, warmup and cosine decay; log training and "
                  "validation loss.",
         ["adamw", "train"], "todo", 5),
        ("build", "Implement temperature and top-k sampling; generate from checkpoints at 1k, "
                  "5k and 10k steps.",
         ["sample"], "todo", None),
        ("build", "Add a KV cache to generation and measure tokens per second before and after.",
         ["kv"], "todo", None),
    ], ("model", "A trained small GPT checkpoint with a short model card and sample generations.",
        ["Validation loss curve included",
         "Samples at three checkpoints",
         "Model card states data, size and known failure modes"])),
]

REMEDIATION_ITEM = (
    "write",
    "Remediation: work three attention examples by hand (2×2 Q, K, V) and check that each row "
    "of weights sums to 1 before the causal-mask step.",
    ["attn"],
)

SIDEBARS = [
    ("math_refresh", "Matrix calculus refresher", 0,
     "- Jacobians of elementwise ops are diagonal\n"
     "- d(Wx)/dx = W; d(Wx)/dW is the outer product with x\n"
     "- Softmax Jacobian: diag(p) − p pᵀ"),
    ("reading_list", "Further reading once the model trains", None,
     "- Scaling-law papers, once you can compare two model sizes yourself\n"
     "- Efficient-attention surveys, once the quadratic cost actually bites"),
]

# Rubric must-include terms per assessed concept (what the Assessor anchors on).
RUBRIC_TERMS: dict[str, list[str]] = {
    "chain": ["local derivative", "upstream gradient"],
    "backprop": ["topological order", "accumulate"],
    "bpe": ["most frequent pair", "merge"],
    "embed": ["lookup", "one-hot"],
    "attn": ["softmax", "scale"],
    "causal": ["mask", "before softmax"],
    "pos": ["permutation", "relative position"],
    "resid": ["gradient path", "normalize"],
}

# (source index, concept key, question, reference answer, key points)
ANCHORS = [
    (0, "attn", "Why are attention logits divided by √d_k before the softmax?",
     "For random q and k with unit-variance components, q·k has variance d_k, so logits grow "
     "with dimension and push the softmax into saturation where gradients vanish; dividing by "
     "√d_k restores unit variance.",
     ["variance grows with dimension", "softmax saturation", "small gradients"]),
    (1, "bpe", "Why does BPE start from characters (or bytes) and merge frequent pairs instead "
               "of starting from whole words?",
     "Starting from characters guarantees every word can be encoded, and merging frequent "
     "pairs builds units for common strings while rare words fall back to smaller pieces.",
     ["open vocabulary", "frequent pairs become units", "rare words decompose"]),
    (2, "lm", "What single objective does the GPT-2 report train on, and why can it cover many "
              "tasks?",
     "Next-token prediction on web text; many tasks appear in natural text as continuations, "
     "so a good enough predictor performs them zero-shot.",
     ["next-token prediction", "tasks as text continuation", "zero-shot"]),
]


@dataclass
class _Probe:
    """One learning action that left an Assessment row (the spine)."""

    ago: timedelta
    kind: str
    concept: str
    score: float
    response: str
    verdict: str
    gaps: list[str] = field(default_factory=list)
    predicted: float | None = None
    baseline: int | None = None  # index into PROBES of the assessment this one re-tests
    anchor: int | None = None  # index into ANCHORS
    item: tuple[int, int] | None = None  # (phase index, item index) the probe was taken on


def _ago(days: float, hours: float = 0) -> timedelta:
    return timedelta(days=days, hours=hours)


# In time order. Scores were chosen so the triangulated verdicts differ across concepts:
# some solid (graded high and corroborated), some verified, some unverified, two shaky.
PROBES: list[_Probe] = [
    _Probe(_ago(20, 3), "self_explanation", "chain", 0.82,
           "Each node only needs its local derivative; backward() multiplies it by the upstream "
           "gradient and passes the product to its inputs.",
           "Clear mechanism: local derivative times upstream gradient, with a worked example."),
    _Probe(_ago(19, 2), "self_explanation", "backprop", 0.55,
           "Backprop runs the chain rule from the loss back to every parameter.",
           "Correct outline, but no ordering argument and no mention of accumulation.",
           ["omitted required element: topological order",
            "omitted required element: accumulate"]),
    _Probe(_ago(17, 4), "productive_failure", "backprop", 0.62,
           "First attempt overwrote gradients for a value used twice; the check failed. Switched "
           "to += and visited nodes in reverse topological order.",
           "Found the reuse bug through struggle; the consolidation landed.",
           baseline=1),
    _Probe(_ago(15, 1), "artifact_review", "chain", 0.84,
           "Blog post with derivations for each op and a failing-then-passing gradient check.",
           "Meets the acceptance criteria; topological ordering could be explained more fully.",
           ["ordering argument is brief"]),
    _Probe(_ago(15, 1), "artifact_review", "backprop", 0.84,
           "Blog post with derivations for each op and a failing-then-passing gradient check.",
           "Meets the acceptance criteria; topological ordering could be explained more fully.",
           ["ordering argument is brief"]),
    _Probe(_ago(14, 3), "self_explanation", "bpe", 0.70,
           "Start from bytes, count adjacent pairs, merge the most frequent pair into a new "
           "symbol, repeat until the vocabulary size is reached.",
           "Mechanism right; didn't say why starting from bytes gives an open vocabulary.",
           ["why bytes: open vocabulary not stated"], item=(1, 0)),
    _Probe(_ago(13, 2), "recall", "chain", 0.78,
           "Local derivative at each node times the gradient flowing in from above; sum over "
           "paths when a value feeds several nodes.",
           "Held cold after two weeks.", baseline=3),
    _Probe(_ago(12, 5), "self_explanation", "embed", 0.68,
           "An embedding is a learned vector per token; looking it up is like multiplying a "
           "one-hot vector by the embedding matrix.",
           "Good equivalence; gradient flow into the table only partly explained.",
           ["only the looked-up rows receive gradient: not stated"]),
    _Probe(_ago(11, 2), "teach", "bpe", 0.80,
           "Explained BPE to a beginner with a worked example on 'low lower lowest'.",
           "Clear for a newcomer; the worked example carried the explanation."),
    _Probe(_ago(10, 3), "calibration", "bpe", 0.76,
           "Merge loop, byte fallback, and why frequent strings become single tokens.",
           "Prediction matched the grade closely.", predicted=0.80),
    _Probe(_ago(9, 4), "calibration", "embed", 0.66,
           "Lookup equals one-hot matmul; only used rows get gradients.",
           "Slightly overconfident, within tolerance.", predicted=0.70),
    _Probe(_ago(9, 1), "source_quiz", "lm", 0.60,
           "It's trained to predict the next token on lots of web text.",
           "Objective right; didn't explain why that covers many tasks.",
           ["tasks as text continuation: missing"], anchor=2),
    _Probe(_ago(8, 2), "recall", "backprop", 0.80,
           "Reverse topological order; each node adds local-gradient × upstream into its "
           "inputs' .grad, which is why reused values accumulate.",
           "Held cold; now includes the ordering argument it lacked before.", baseline=4),
    _Probe(_ago(7, 3), "self_explanation", "resid", 0.74,
           "The residual stream gives gradients a direct path; LayerNorm keeps activations at "
           "a stable scale.",
           "Solid; pre- vs post-norm placement not discussed.",
           ["pre-LN vs post-LN placement"]),
    _Probe(_ago(7, 1), "teach", "resid", 0.70,
           "Explained residual connections as 'adding a correction' to the stream.",
           "Good intuition; normalization part was thin."),
    _Probe(_ago(6, 4), "self_explanation", "attn", 0.42,
           "Attention compares each token with every other token and takes a weighted average.",
           "Describes what, not why: no softmax normalization argument and no scaling.",
           ["no mechanism for the weights summing to 1",
            "omitted required element: softmax", "omitted required element: scale"],
           item=(2, 0)),
    _Probe(_ago(5, 2), "self_explanation", "pos", 0.58,
           "Without positions attention can't tell word order; sinusoids add a position "
           "signal.",
           "Correct need; relative-position property not explained.",
           ["omitted required element: relative position"]),
    _Probe(_ago(4, 3), "calibration", "attn", 0.50,
           "Softmax over q·k scores, scaled so they don't get too big.",
           "Felt confident but the scaling argument is still hand-wavy.", predicted=0.85,
           baseline=15),
    _Probe(_ago(3, 2), "self_explanation", "causal", 0.35,
           "The mask hides future tokens by zeroing their attention weights.",
           "Zeroing after softmax breaks normalization; the mechanism is wrong.",
           ["mask applied after softmax", "omitted required element: before softmax"],
           item=(2, 2)),
    _Probe(_ago(2, 5), "productive_failure", "causal", 0.40,
           "Tried zeroing weights after softmax, saw rows no longer summed to 1, then tried "
           "renormalizing.",
           "Struggled productively toward the right idea; not there yet.", baseline=18),
    _Probe(_ago(1, 4), "self_explanation", "attn", 0.66,
           "Weights are softmax(QKᵀ/√d_k): dividing by √d_k scales the logits' variance back "
           "to about 1 so the softmax doesn't saturate; each row sums to 1.",
           "Much improved: scaling argument now present.", ["variance derivation is brief"],
           baseline=17),
    _Probe(_ago(0, 20), "recall", "bpe", 0.79,
           "Count pairs, merge the most frequent, repeat; starting from bytes means nothing is "
           "ever out of vocabulary.",
           "Held cold, and now includes the open-vocabulary reason.", baseline=9),
]

# Which prompt grades each probe kind in the real app (every other kind goes through
# assess_concept's GRADE, rendered at the default strictness), so the demo rows carry the
# prompt_tag a real grade would.
_GRADE = grade_prompt()
_GRADED_BY = {"teach": TEACH, "productive_failure": PF_CONSOLIDATE,
              "artifact_review": ASSESS_ARTIFACT}

# (concept key, front, back, status, reps, interval days, due offset in days from now)
CARDS = [
    ("chain", "What does the chain rule let backward() compute at each node?",
     "The local derivative of the node's output with respect to each input, multiplied by the "
     "upstream gradient.", "active", 3, 6, 2.0),
    ("backprop", "Why does backward() accumulate gradients with += ?",
     "A value used in several places receives gradient from each use; the contributions sum.",
     "active", 2, 3, -0.3),
    ("bpe", "What does one BPE merge step do?",
     "Counts adjacent symbol pairs and replaces the most frequent pair with a new symbol.",
     "active", 2, 4, 1.0),
    ("embed", "An embedding lookup is equivalent to which matrix operation?",
     "Multiplying a one-hot row vector by the embedding matrix.", "active", 1, 1, -0.1),
    ("attn", "Why divide attention logits by √d_k?",
     "q·k has variance d_k for unit-variance components; scaling keeps the softmax out of "
     "saturation.", "active", 0, 0, -0.5),
    ("causal", "What does the causal mask set, and to what value?",
     "Scores for future positions (j > i) are set to −∞ before the softmax, so their weights "
     "are 0.", "proposed", 0, 0, 0.0),
    ("causal", "Is the causal mask applied before or after the softmax?",
     "Before: masking after it leaves rows that no longer sum to 1.", "proposed", 0, 0, 0.0),
    ("lm", "For a one-hot target, cross-entropy reduces to what?",
     "The negative log of the probability assigned to the correct token.", "suspended", 1, 1,
     3.0),
]

# Decay checks: (concept key, due offset in days from now). Negative = due now.
DECAY_DUE = [
    ("backprop", -1.0), ("lm", -2.0), ("pos", -0.25),
    ("chain", 2.0), ("bpe", 6.0), ("embed", 3.0), ("resid", 1.0), ("attn", 2.0),
    ("causal", 1.0),
]

# Tutor sessions: (concept key, when, messages). Each message is (role, text, minutes after the
# conversation started). Role "attempt" is a learner message sent with Submit attempt: it is
# stored as a user message marked is_attempt, with an accepted Attempt row.
CHAIN_MESSAGES = [
    ("user", "For c = a * b, why is dc/da equal to b? It feels like I'm memorizing it.", 0),
    ("tutor", "Try it numerically before I say anything: nudge a by a small h, keep b fixed, "
              "and see how much c moves. What do you get, divided by h?", 1),
    ("attempt", "c(a + h) - c(a) = (a + h)b - ab = hb, and dividing by h gives b. So the "
                "local derivative is just the other input.", 5),
    ("tutor", "Exactly, and you derived it rather than recalled it. In backward() that node "
              "multiplies the upstream gradient by b for a, and by a for b; the chain rule is "
              "that product, applied node by node.", 6),
]
TUTOR_MESSAGES = [
    ("user", "I get that the mask stops a token from seeing the future, but why does it have "
             "to go in before the softmax? Can't I just zero the future weights afterwards?", 0),
    ("tutor", "Good thing to sit with before I say anything. What has to be true of each row "
              "of attention weights after the softmax? Take one row of a 3×3 example, zero the "
              "future entries, and check that property.", 1),
    ("user", "Each row should sum to 1. If I zero entries after the softmax, the first row "
             "keeps only one weight, so it sums to less than 1. So I'd have to renormalize?", 6),
    ("tutor", "Exactly, you've found the problem. Renormalizing afterwards is equivalent to "
              "something you can do in one step. What value could you put in the logits so "
              "that the softmax itself gives those positions zero weight?", 7),
    ("attempt", "Set the masked logits to `-inf` before the softmax. Since `exp(-inf)` is 0, they get "
                "zero weight and the rest still sum to 1. In code: "
                "`scores.masked_fill(mask == 0, float('-inf'))`", 12),
    ("tutor", "That's the mechanism. Since you've submitted a real attempt, here's the full "
              "picture: masking with −∞ before the softmax is the same as renormalizing over "
              "the allowed positions, but it's one fused, numerically clean step. One thing to "
              "test in your implementation: the first row has a single unmasked entry, so "
              "`weights[0, 0]` must be exactly 1.", 13),
]

# My notes on one concept (the concept notebook), written after its tutor session.
DEMO_NOTE = ("causal", _ago(3, 0), (
    "Mask before the softmax, not after.\n\n"
    "- Set future logits to -inf, so exp gives exact zeros and each row still sums to 1.\n"
    "- Zeroing after the softmax breaks the sum, and renormalizing just recomputes the same "
    "thing the long way.\n\n"
    "Next: check how the KV cache keeps the same mask during generation."))

TUTOR_SESSIONS = [
    ("chain", _ago(20, 5), CHAIN_MESSAGES),
    ("causal", _ago(3, 1), TUTOR_MESSAGES),
]


# --- builder --------------------------------------------------------------------------------


def _utcnow() -> datetime:
    """Naive UTC, like every datetime SQLite hands back."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def find_demo(session: Session) -> Topic | None:
    return session.exec(
        select(Topic).where(col(Topic.is_demo).is_(True)).order_by(Topic.id)
    ).first()


def build_demo(session: Session, *, now: datetime | None = None) -> Topic:
    """Create the demo topic and everything its pages read. Commits once at the end."""
    now = (now or _utcnow()).replace(tzinfo=None)
    start = now - _ago(22, 6)

    def at(ago: timedelta) -> datetime:
        return now - ago

    events: list[tuple[datetime, dict]] = []

    def emit(when: datetime, kind: str, detail: str = "", **target: int) -> None:
        events.append((when, {"kind": kind, "detail": detail, **target}))

    topic = Topic(title=DEMO_TITLE, is_demo=True, created_at=start)
    session.add(topic)
    session.flush()
    tid = topic.id
    session.add(TopicIntent(topic_id=tid, created_at=start, **INTENT))

    # Research: foundation + tiered reading list (the Researcher's output, reviewed).
    research_at = start + timedelta(minutes=4)
    names = CONCEPTS
    session.add(TopicFoundation(
        topic_id=tid, overview=OVERVIEW, created_at=research_at,
        key_concepts=list(names.values()),
        prerequisite_map={names[k]: [names[p] for p in v] for k, v in PREREQUISITES.items()},
    ))
    angles = list(dict.fromkeys(s[3] for s in SOURCES))
    emit(start + timedelta(minutes=1), "research:plan", f"{len(angles)} briefs", topic_id=tid)
    for angle in angles:
        found = sum(1 for s in SOURCES if s[3] == angle)
        emit(start + timedelta(minutes=3), "research:subagent", f"{angle}: {found} sources",
             topic_id=tid)
    emit(research_at, "prompt", RESEARCH_FOUNDATION.tag, topic_id=tid)
    emit(research_at, "research:synth", f"{len(names)} key concepts", topic_id=tid)
    emit(research_at, "research:done", f"{len(SOURCES)} sources proposed", topic_id=tid)

    sources: list[SourceDoc] = []
    for rank, (title, url, tier, angle, summary, why, status) in enumerate(SOURCES):
        doc = SourceDoc(topic_id=tid, title=title, url=url, tier=tier, summary=summary, why=why,
                        relevance=round(0.95 - 0.05 * rank, 2), rank=rank, angle=angle,
                        status=status, created_at=research_at)
        session.add(doc)
        sources.append(doc)
    session.flush()
    for doc in sources:
        if doc.status == "accepted":
            # Stand-in for the fetched page text: the Researcher's own summary of it.
            index_text(session, kind="source_doc", text=f"{doc.summary} {doc.why}",
                       source_ref=f"sourcedoc:{doc.id}", topic_id=tid, heading=doc.title)

    # Curriculum: track, phases, items, deliverables, sidebars, concepts + estimates, graph.
    curriculum_at = start + timedelta(hours=1)
    track = Track(topic_id=tid, title=topic.title,
                  overview="Four phases, each ending in something you ship: an autograd "
                           "engine, a tokenizer, an attention ablation, and a trained model.")
    session.add(track)
    session.flush()
    phases: list[Phase] = []
    items: list[list[Item]] = []
    for position, (title, hours, flags, phase_items, (dkind, dtext, criteria)) in enumerate(
        PHASES
    ):
        phase = Phase(track_id=track.id, title=title, position=position, est_hours=hours,
                      flags=flags)
        session.add(phase)
        session.flush()
        phases.append(phase)
        rows: list[Item] = []
        for i, (itype, text, refs, status, src) in enumerate(phase_items):
            row = Item(phase_id=phase.id, text=text, type=itype, status=status, position=i,
                       concept_refs=[names[r] for r in refs],
                       source_doc_id=sources[src].id if src is not None else None)
            session.add(row)
            rows.append(row)
        items.append(rows)
        session.add(Deliverable(phase_id=phase.id, kind=dkind, text=dtext,
                                acceptance_criteria=criteria))
    for position, (kind, title, phase_index, body) in enumerate(SIDEBARS):
        session.add(Sidebar(track_id=track.id, kind=kind, title=title, body=body,
                            position=position,
                            phase_id=phases[phase_index].id if phase_index is not None else None))

    foundation_map = {names[k]: [names[p] for p in v] for k, v in PREREQUISITES.items()}
    load_bearing = load_bearing_concepts(foundation_map)
    concepts: dict[str, Concept] = {}
    for key, name in names.items():
        concept = Concept(track_id=track.id, name=name, is_load_bearing=name in load_bearing)
        session.add(concept)
        concepts[key] = concept
    session.flush()
    pairs, unresolved = graph.edges_from_prerequisite_map(foundation_map,
                                                          list(concepts.values()))
    inserted = graph.insert_edges(session, pairs, kind="prerequisite", origin="researcher",
                                  origin_ref=f"foundation:{tid}")
    for edge in session.exec(
        select(ConceptEdge).where(ConceptEdge.origin_ref == f"foundation:{tid}")
    ).all():
        edge.valid_from = edge.recorded_at = curriculum_at
    emit(curriculum_at, "curriculum:plan", f"{len(names)} concepts, "
         f"{sum(1 for s in SOURCES if s[6] == 'accepted')} sources", topic_id=tid)
    emit(curriculum_at, "prompt", CURRICULUM.tag, topic_id=tid)
    emit(curriculum_at, "curriculum:generated", f"{len(PHASES)} phases", topic_id=tid)
    emit(curriculum_at, "curriculum:spaced", "1 revisit item(s) injected", topic_id=tid)
    emit(curriculum_at, "graph:edges", f"{inserted} edges, {len(unresolved)} unresolved",
         topic_id=tid)
    emit(curriculum_at, "curriculum:concepts",
         f"{len(names)} concepts, {len(load_bearing)} load-bearing", topic_id=tid)
    emit(curriculum_at, "curriculum:done", f"track {track.id}", topic_id=tid)

    # Source-grounded quiz anchors and the rubrics the Assessor grades against.
    anchors_at = now - _ago(10, 6)
    emit(anchors_at, "anchors:plan", f"{len(ANCHORS)} source(s)", topic_id=tid)
    anchor_rows: list[ReferenceAnchor] = []
    for src, key, question, answer, points in ANCHORS:
        anchor = ReferenceAnchor(source_doc_id=sources[src].id, concept_id=concepts[key].id,
                                 question=question, reference_answer=answer, key_points=points,
                                 created_at=anchors_at)
        session.add(anchor)
        anchor_rows.append(anchor)
        emit(anchors_at, "prompt", ANCHOR.tag, topic_id=tid)
        emit(anchors_at, "anchors:subagent", f"source {sources[src].id}: 1 anchor(s)",
             topic_id=tid)
    emit(anchors_at, "anchors:done", f"{len(ANCHORS)} anchor(s) created", topic_id=tid)

    rubrics: dict[str, Rubric] = {}
    first_probe = {p.concept: p for p in reversed(PROBES)}
    for key, terms in RUBRIC_TERMS.items():
        made_at = at(first_probe[key].ago) - timedelta(minutes=2)
        rubric = Rubric(
            concept_id=concepts[key].id, created_at=made_at, must_include=terms,
            criteria=[f"Explains the mechanism of {names[key].lower()}, not just its definition",
                      "Gives a concrete, checkable example",
                      "States when or why it matters for training a language model"],
            strong_signs=["derives the result rather than asserting it"],
            weak_signs=["describes what happens without why"],
            source_refs=[], reviewed_by_user=key in {"chain", "attn"},
        )
        session.add(rubric)
        rubrics[key] = rubric
        emit(made_at, "prompt", RUBRIC.tag, topic_id=tid)
    session.flush()

    # The Assessment spine, in time order (ids follow time, as the dashboard trend expects).
    rows: list[Assessment] = []
    for probe in PROBES:
        when = at(probe.ago)
        concept = concepts[probe.concept]
        baseline = rows[probe.baseline] if probe.baseline is not None else None
        prompt = {
            "self_explanation": f"Explain {concept.name}: the mechanism, not the definition.",
            "calibration": f"Predict your score, then explain {concept.name}.",
            "recall": DECAY_RECALL.format(concept=concept.name),
            "teach": f"Teach: {concept.name}",
            "artifact_review": f"Ship: {PHASES[0][4][1][:80]}",
            "productive_failure": f"Before any instruction, attempt a problem on "
                                  f"{concept.name}.",
            "source_quiz": ANCHORS[probe.anchor][2] if probe.anchor is not None else "",
        }[probe.kind]
        a = Assessment(
            concept_id=concept.id, kind=probe.kind, prompt=prompt, response=probe.response,
            verdict=probe.verdict, score=probe.score, gaps=probe.gaps, created_at=when,
            confidence_predicted=probe.predicted,
            confidence_actual=probe.score if probe.predicted is not None else None,
            rubric_id=rubrics[probe.concept].id if probe.concept in rubrics
            and probe.kind in {"self_explanation", "calibration", "recall"} else None,
            anchor_id=anchor_rows[probe.anchor].id if probe.anchor is not None else None,
            baseline_assessment_id=baseline.id if baseline else None,
            delta=round(probe.score - baseline.score, 4) if baseline else None,
            item_id=items[probe.item[0]][probe.item[1]].id if probe.item else None,
            # The current tag of the prompt that grades this kind in the real app, the same
            # one the trace below stamps for this row.
            prompt_tag=_GRADED_BY.get(probe.kind, _GRADE).tag,
        )
        session.add(a)
        session.flush()
        rows.append(a)
        index_assessment(session, a, topic_id=tid)
        level = level_from_score(probe.score)[0]
        if probe.kind == "teach":
            emit(when, "prompt", TEACH.tag, topic_id=tid)
        elif probe.kind == "productive_failure":
            emit(when - timedelta(minutes=20), "prompt", PF_GENERATE.tag, topic_id=tid)
            emit(when, "prompt", PF_CONSOLIDATE.tag, topic_id=tid)
        elif probe.kind == "artifact_review":
            if probe.concept == "chain":  # one ship reviews both phase concepts
                emit(when, "prompt", ASSESS_ARTIFACT.tag, topic_id=tid)
                emit(when, "artifact:reviewed", f"score={probe.score}, 2 concept(s)",
                     topic_id=tid)
        else:
            emit(when, "assess:probe", probe.kind, topic_id=tid)
            emit(when, "prompt", _GRADE.tag, topic_id=tid)
            hard = [g for g in probe.gaps if g.startswith("omitted required element")]
            if hard:
                emit(when, "assess:rules", f"{len(hard)} hard gap(s)", topic_id=tid)
            emit(when, "assess:graded", f"score={probe.score}", topic_id=tid)
            emit(when, "assess:estimate", f"level={level}", topic_id=tid)
            emit(when, "assess:done", f"concept {concept.id}", topic_id=tid)

    # Phase 1 shipped (its review wrote the artifact_review rows above).
    ship = session.exec(select(Deliverable).where(Deliverable.phase_id == phases[0].id)).one()
    ship.artifact_url = "https://example.com/demo/autograd-in-100-lines"
    ship.review_verdict = PROBES[3].verdict

    # Remediation after the weak attention probe: one item placed into Phase 3.
    remediate_at = at(PROBES[15].ago) + timedelta(minutes=10)
    rtype, rtext, rrefs = REMEDIATION_ITEM
    session.add(Item(phase_id=phases[2].id, text=rtext, type=rtype, status="todo",
                     position=len(items[2]), concept_refs=[names[r] for r in rrefs],
                     added_by="remediation", remediation_key=f"attn:{rows[15].id}"))
    emit(remediate_at, "remediate:probe", "2 open gap(s)", topic_id=tid)
    emit(remediate_at, "prompt", REMEDIATE.tag, topic_id=tid)
    emit(remediate_at, "remediate:generated", "1 item(s)", topic_id=tid)
    emit(remediate_at, "remediate:placed", f"phase {phases[2].position}", topic_id=tid)
    emit(remediate_at, "remediate:done", f"concept {concepts['attn'].id}", topic_id=tid)

    # Knowledge estimates, as the Assessor leaves them: the latest probe it graded per concept
    # (teaching, productive failure and the ship review never write the estimate); the rest
    # not yet measured.
    latest = {p.concept: p for p in PROBES if p.kind in GRADING_KINDS}
    for key, concept in concepts.items():
        if key in latest:
            level, confidence = level_from_score(latest[key].score)
            updated = at(latest[key].ago)
        else:
            level, confidence, updated = "medium", 0.3, curriculum_at
        session.add(KnowledgeEstimate(concept_id=concept.id, level=level,
                                      confidence=confidence, updated_at=updated))

    # Retention: curated cards (some due now, two freshly proposed) and decay checks.
    retention_at = at(PROBES[18].ago) + timedelta(minutes=5)
    emit(retention_at, "prompt", RETENTION.tag, topic_id=tid)
    for key, front, back, status, reps, interval, due_in in CARDS:
        created = (retention_at if status == "proposed"
                   else at(first_probe[key].ago) + timedelta(minutes=5))
        session.add(SRSCard(concept_id=concepts[key].id, front=front, back=back,
                            source_ref=f"assessment:{rows[18].id}" if status == "proposed"
                            else "", status=status, reps=reps, interval=interval,
                            ease=2.5 if reps < 2 else 2.6, due_at=now + timedelta(days=due_in),
                            last_result="good" if reps else "", created_at=created))
    for key, due_in in DECAY_DUE:
        prompt = RecallPrompt(concept_id=concepts[key].id,
                              prompt=DECAY_RECALL.format(concept=names[key]), status="active",
                              due_at=now + timedelta(days=due_in),
                              last_result="held" if key in {"chain", "backprop", "bpe"} else "",
                              created_at=at(first_probe[key].ago))
        session.add(prompt)
        session.flush()
        index_question(session, text=prompt.prompt, source_ref=f"recallprompt:{prompt.id}",
                       topic_id=tid, concept_id=concepts[key].id)

    # Tutor: Socratic conversations in which the learner submitted an attempt before the reveal.
    for key, ago, script in TUTOR_SESSIONS:
        convo_at = at(ago)
        tutor_concept = concepts[key]
        convo = Conversation(topic_id=tid, concept_id=tutor_concept.id, attempt_logged=True,
                             created_at=convo_at)
        session.add(convo)
        session.flush()
        # The estimate as it stood then: unmeasured (medium) or graded low.
        level = "medium" if at(first_probe[key].ago) > convo_at else "low"
        levels = compute_levels(KnowledgeEstimate(concept_id=tutor_concept.id, level=level))
        after_attempt = False
        for role, content, minutes in script:
            when = convo_at + timedelta(minutes=minutes)
            is_attempt = role == "attempt"
            # The tutor's reply to an accepted attempt is the worked solution it revealed.
            reveals = role == "tutor" and after_attempt
            after_attempt = is_attempt
            message = Message(conversation_id=convo.id, role="tutor" if role == "tutor" else "user",
                              content=content, is_attempt=True if is_attempt else None,
                              reveals_solution=True if reveals else None, created_at=when)
            session.add(message)
            session.flush()
            index_message(session, message, concept_id=tutor_concept.id, topic_id=tid,
                          levels=levels if role == "tutor" else None)
            if role == "tutor":
                continue
            emit(when, "levels", f"assistance={levels.assistance} challenge={levels.challenge}",
                 conversation_id=convo.id)
            if is_attempt:
                # As engine/attempt.py records it: checked, accepted, then the tutor runs.
                session.add(Attempt(conversation_id=convo.id, concept_id=tutor_concept.id,
                                    message_id=message.id, accepted=True, created_at=when))
                emit(when, "attempt:submitted", SUBMITTED_DETAIL, conversation_id=convo.id)
                emit(when, "prompt", TUTOR_SOLUTION_GUARD.tag, conversation_id=convo.id)
                emit(when, "guard:attempt_checked", "source=model attempted=true",
                     conversation_id=convo.id)
                emit(when, "attempt:accepted", OUTCOME_DETAILS[ACCEPTED],
                     conversation_id=convo.id)
                emit(when, "prompt", TUTOR_ATTEMPT_ACCEPTED.tag, conversation_id=convo.id)
            emit(when, "prompt", TUTOR_BASE.tag, conversation_id=convo.id)
            emit(when, "llm_call", "step=1", conversation_id=convo.id)
            if is_attempt:
                emit(when, "tool:reveal_solution:allowed", conversation_id=convo.id)
                emit(when, "llm_call", "step=2", conversation_id=convo.id)

    # The learner's own notes on the concept they worked through with the tutor.
    note_key, note_ago, note_body = DEMO_NOTE
    session.add(ConceptNote(concept_id=concepts[note_key].id, body=note_body,
                            updated_at=at(note_ago)))

    # The trace, written in time order so its ids read chronologically.
    for when, fields in sorted(events, key=lambda e: e[0]):
        session.add(AgentEvent(created_at=when, **fields))

    session.commit()
    session.refresh(topic)
    return topic


def ensure_demo(session: Session, *, now: datetime | None = None) -> tuple[Topic, bool]:
    """Return the demo topic, building it first if there is none. (topic, created)."""
    with _LOCK:
        existing = find_demo(session)
        if existing is not None:
            return existing, False
        return build_demo(session, now=now), True


# --- removal --------------------------------------------------------------------------------


def _owned_rows(session: Session, topic_id: int) -> dict[Table, set[int]]:
    """Every row that belongs to the topic: the closure of rows referencing it, through every
    foreign key in the schema (so a table added later is covered without touching this)."""
    tables = SQLModel.metadata.sorted_tables
    referrers: dict[Table, list] = defaultdict(list)
    for table in tables:
        for fk in table.foreign_keys:
            referrers[fk.column.table].append((table, fk.parent))
    topic_table = Topic.__table__
    owned: dict[Table, set[int]] = defaultdict(set)
    owned[topic_table].add(topic_id)
    frontier: list[tuple[Table, set[int]]] = [(topic_table, {topic_id})]
    while frontier:
        table, ids = frontier.pop()
        for child, column in referrers[table]:
            found = set(
                session.execute(sa_select(child.c.id).where(column.in_(ids))).scalars()
            )
            new = found - owned[child]
            if new:
                owned[child] |= new
                frontier.append((child, new))
    return owned


def remove_demo(session: Session, topic_id: int | None = None) -> bool:
    """Delete a demo topic and every row that belongs to it: the one with `topic_id`, or the
    oldest demo when no id is given. False when there is no such demo topic (a non-demo
    topic's id is never deleted here)."""
    with _LOCK:
        if topic_id is None:
            topic = find_demo(session)
        else:
            topic = session.get(Topic, topic_id)
            if topic is not None and not topic.is_demo:
                topic = None
        if topic is None:
            return False
        owned = _owned_rows(session, topic.id)
        session.flush()
        # Self-references (an assessment's baseline) would block row-by-row deletes.
        for table, ids in owned.items():
            for fk in table.foreign_keys:
                if fk.column.table is table:
                    session.execute(update(table).where(table.c.id.in_(ids))
                                    .values({fk.parent.name: None}))
        # Children before parents, so every delete satisfies foreign_keys=ON as it runs.
        for table in reversed(SQLModel.metadata.sorted_tables):
            ids = owned.get(table)
            if ids:
                session.execute(delete(table).where(table.c.id.in_(ids)))
        session.commit()
        return True
