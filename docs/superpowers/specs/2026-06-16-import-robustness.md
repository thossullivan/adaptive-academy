# Robust Markdown Import — Spec

**Date:** 2026-06-16
**Milestone:** Plan 7 (hardening, found by dogfooding a real tracker)
**Status:** Approved (focused; user requested "bring my real tracker in")

## 1. Problem

`markdown_to_track` only accepts the tool's **own canonical export** (`## Phase N — title`
headings; `- [box] (type) text` items). Importing a real hand-written tracker
(`llm-from-scratch-tracker.md`) produced **13 phases and 0 items**: every checkbox dropped
(no `(type)` prefix), and prose headings (`## How to use this`, `## Math foundations`) became
empty phantom phases. Goal: a real tracker imports with its items intact, without breaking the
canonical round-trip.

## 2. Locked decisions

- **§2.1 Untyped checkbox items are accepted.** Items of the form `- [box] text` (no `(type)`
  prefix) parse, with a **deterministic type inference** (`_infer_type`): `watch` (video /
  lecture / 3blue1brown / youtube), `build` (build / train / implement / code / run / curate /
  replicate), `write` (blog / writeup / write-up / post / document), else `read`. Order:
  watch → build → write → read; first match wins. Canonical `- [box] (type) text` items still
  take their explicit type (tried first).
- **§2.2 Heading classification (the round-trip-safe rule).** A `## ` heading becomes a
  **phase** iff it (a) matches the canonical `Phase \d+ — …` form, OR (b) its body contains at
  least one checkbox item or a `🎯 Ship` line. Otherwise it becomes a **reference sidebar**
  (title = heading, body = its prose). This preserves the canonical round-trip (canonical
  phases always match `Phase N —`, even a phase whose only content is a Ship) while turning
  real prose sections (`How to use this`) into sidebars and content sections
  (`Math foundations`, `Track B — …`) into phases that keep their items.
- **§2.3 Non-phase, non-checkbox headings → sidebars, not dropped.** Their prose body is
  preserved as the sidebar body (kind `reference`). Non-checkbox bullets (`- text` without
  `[ ]`) inside such a section are kept as part of the body text.
- **§2.4 Block-based parse.** `markdown_to_track` is restructured to first split the body into
  `(heading, body_lines)` blocks at each `## `, then classify each block — a lookahead the
  current single-pass parser can't do. Title + overview handling is unchanged.
- **§2.5 Export is unchanged.** `track_to_markdown` still emits the canonical typed form; this
  is import-only leniency. A real tracker imported then re-exported becomes canonical (typed
  items, inferred types) — a one-way normalization, which is the desired behaviour (it pulls
  external trackers *into* the tool's model).

## 3. Definition of done

- The real `llm-from-scratch-tracker.md` imports with **all ~40 checkbox items** preserved,
  Phases 0–4 + Track B + Math foundations as phases (with items), and prose sections
  (`How to use this`, framing) as sidebars — **zero items dropped**.
- Canonical round-trip (`track_to_markdown` → `markdown_to_track`) is **byte-for-structure
  identical** to today (all existing `test_track_markdown` tests pass unchanged, incl. a
  canonical phase whose only content is a Ship).
- `_infer_type` is pure and unit-tested; untyped-item and heading-classification paths are
  unit-tested; the import API path persists the inferred items.
- No migration; Plans 1–6 paths intact; ruff clean.

## 4. Out of scope

Arbitrary markdown (tables, nested lists, non-`##` phase headers); preserving non-checkbox
bullet structure as items; round-tripping the inferred types back to "untyped"; a file-upload
UI (import endpoint already exists; wiring a richer import UI is a later UX pass).
