# The Voyage — wayfinding momentum (persistence layer) — design

**Date:** 2026-06-17
**Status:** design approved (brainstorm); pending spec review → implementation plan
**Theme:** local-first, single-user, dogfooded. Honors the anti-Goodhart competence philosophy.

## Why

The tool has an exquisite model of *what you know* (five triangulated competence signals) and
**zero** model of *whether you'll keep going*. The #1 killer of self-directed adult learning isn't
forgetting — it's **abandonment** (quitting in month 3 of a 12-month, 520-hour commitment). This
adds the missing **persistence layer**: a forgiving, game-like "momentum" system themed on the
existing Wayfinder ("The Voyage").

**Delight is load-bearing, not decoration.** For a tool whose whole job is keeping the learner in
the chair for a year, immersive joy directly serves the anti-abandonment goal. (The user also
values that their kids would enjoy it — a signal that playfulness is a feature.)

## Core model — distance vs. wind

Two orthogonal quantities on the same voyage:

- **Distance** = real curriculum progress (phases/concepts done). Already exists; the competence
  system owns it. Momentum NEVER alters distance.
- **Wind / momentum** = NEW. A *velocity* that builds when you do real learning and decays when you
  don't. High wind = cruising; dying wind = early warning; becalmed = the abandonment risk.

Decisions locked in brainstorming:

1. **Core loop:** long-arc momentum (a voyage that drifts, never a streak that shatters). Recovery =
   catching the current again; a lapse never resets distance.
2. **Propulsion (what fills the sails):** *any real completed learning action* — not page views,
   not setup. The action must be *done*, not merely opened.
3. **Recovery:** a **comeback quest** (anti-guilt). Gentle decay + one high-value re-entry move that
   visibly restores wind. **No currency/gems** to manage.
4. **Scope:** **per-voyage wind + a Fleet view** (cross-topic). The Fleet doubles as the
   "whole learning life" surface the tool lacks today.

## Architecture — pure-derived, with a C-shaped seam

**Derived from the event log (no new tables, no cron, no sync).** `AgentEvent` already timestamps
every meaningful action. Wind is computed on the fly from those timestamps, so it **decays
correctly even if the app is never opened**. This fits the event-sourced/observable architecture.

**No placeholder schema.** The comeback-quest logic lives behind one function boundary
(`comeback_move(...)`) that today computes purely from events and *could* later read/write state
without any caller changing — a **seam, not a stub**. If state is ever needed, it's a ~10-minute
drop-in whose shape we'll know from real use. (This was an explicit YAGNI decision: unused columns
cost migrations, dead code, and lies-to-readers; a derivable system shouldn't pre-commit storage.)

### Wind engine (`src/adaptive_academy/engine/momentum.py`)

- **`QUALIFYING_KINDS`**: the `AgentEvent.kind`s that count as real learning — assessment grades,
  productive-failure attempts, teach-backs, artifact ships (`artifact:reviewed`), decay recalls, a
  tutor session with generative effort. Explicitly **excludes** research/curriculum *generation*
  (setup) and any view/navigation events.
- **Decay formula:** `wind = Σ over qualifying events e of 0.5 ** (age_days(e) / HALF_LIFE)`, with
  `HALF_LIFE ≈ 3 days` (≈ a week of silence → ~¼ wind). v1 weights all actions equally (matches
  "any real action"); per-kind weighting is deferred.
- **States** (legible, mirroring competence verdicts): **Cruising · Steady · Fading · Becalmed**,
  by thresholds on the decayed wind + recency, *calibrated so ~3–4 real sessions/week (the user's
  ~10–12 hr/week) holds Steady or better*. Thresholds are tunable constants, set in implementation.
- **`wind(session, topic_id, now=utcnow)` → `WindState(value, state, last_sailed)`** — `now` is
  injectable for hermetic tests.
- **`fleet(session, now=utcnow)` → list[per-topic `WindState`]**, sorted attention-first (becalmed
  → fading → steady → cruising).
- **`comeback_move(session, topic_id) → Move | None`** (the C-seam): when Fading/Becalmed, pick ONE
  high-value, low-friction move (~15–30 min "minimum viable session"). Priority: an overdue decay
  check → the next undone curriculum item in the current phase → a quick self-explanation on a
  load-bearing concept. Returns `None` when the voyage is healthy.

### API
- `GET /api/fleet` → all voyages' `WindState`.
- `GET /api/topics/{id}/wind` → one voyage's `WindState`.
- `GET /api/topics/{id}/comeback` → the comeback `Move` (or null).

## Representation (chosen via visual brainstorm)

- **Wayfinder sea-state (option C).** The existing Wayfinder gains an atmospheric layer driven by
  wind: wind streaks + lively water when sailing, **flat and still when becalmed** (the contrast
  does the motivational work). The most immersive option — chosen deliberately for delight.
- **Fleet view — harbor panorama (B) as hero, collapsing to sea-tiles (A) for quick mornings.**
  A new **global** (not topic-scoped) page. Hero: one shared ocean, each ship's height = progress
  toward its North Star, liveliness = momentum. A toggle collapses to scannable sea-tiles with
  **becalmed voyages floated to the top** demanding wind.
- **Comeback card on Today — adaptive tone.** Same mechanic (one move → wind returns); tone reads
  the severity: a short fade → playful ("a breeze on the horizon… set sail"); a long/heavy
  becalming → warm and gentle ("your voyage is waiting; one good move catches the wind") — because
  that's exactly when twee would sting. Also surfaced for becalmed voyages in the Fleet.

## Anti-Goodhart guardrails (non-negotiable)

- Wind is **information to help, never a score to beat.** No leaderboard, no public streak count.
- Momentum **never touches the competence verdicts** — the two systems are independent; you can be
  cruising while shaky, or becalmed while solid.
- Supportive framing only; **no shame**. A lapse is "becalmed," not "you broke your streak." The
  comeback reframes the return as a win.
- Because propulsion is "real action," not time-on-task, it resists grind-gaming.

## Accessibility & performance
- Respect `prefers-reduced-motion`: animation → static intensity (sea-state still legible, just not
  moving). Keep the atmosphere cheap (CSS/SVG, no heavy canvas loops).

## Build slices (each TDD'd, each routed to main)
1. **Wind engine** `engine/momentum.py`: qualifying kinds, decay formula, states, fleet aggregation,
   `comeback_move` (the seam). Pure-ish; TDD with seeded `AgentEvent`s + injected `now`.
2. **API**: `/api/fleet`, `/api/topics/{id}/wind`, `/api/topics/{id}/comeback`.
3. **Frontend**: Fleet page (B→A), Wayfinder sea-state layer, Today comeback card with adaptive
   tone, reduced-motion handling.

## Out of scope (deferred)
- Gems / bankable currency / streak-freezes (we chose the comeback quest instead).
- Push notifications / background cron (unnecessary — wind is derived, decays without a job).
- Cross-device sync; per-action-type weighting; storing momentum history.
- Comeback-quest *state* (only if the derived version proves insufficient — the seam is ready).
