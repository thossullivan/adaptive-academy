# Three "tie-it-together" features

**Goal:** Add three high-impact features on top of the Observatory frontend that map onto the past · present · future of a learning journey and make the command center feel alive.

## 1. Concept Constellation (`/topics/[id]/map`)
A force-directed star map of the topic's concepts.
- **Nodes** = curriculum concepts; radius larger for `is_load_bearing`; fill color by mastery level (high=success, medium=accent, low=danger, unknown=faint) derived from the latest assessment's `estimate_level` per concept (same derivation as the dashboard).
- **Edges** = `TopicFoundation.prerequisite_map` (`{concept_name: [prereq_names]}`), drawn only between names that resolve to curriculum concepts (lenient normalized match). Isolated nodes still render.
- Built with LayerChart's `ForceSimulation` + `Link` + `Circle`, or a hand-rolled d3-force if simpler. Hover shows concept name + level; click → tutor for that concept.
- Pure frontend; composes `getCurriculum` + `getFoundation` + per-concept `listAssessments`.

## 2. Today's Session (`/topics/[id]/today`)
The "what do I do right now" guided loop, composed from real state:
1. **Warm up** — due SRS cards (`listRetention due`), if any.
2. **Build** — the next 1–3 `todo`/`doing` track items in phase order.
3. **Probe** — a targeted assessment of the shakiest *load-bearing* concept (lowest `estimate_level`), linking to `/assess`.
4. **Teach back** — a tutor warm-up link for that concept.
Each block is a card with a primary action that routes into the existing pages. Pure frontend orchestration; no backend change.

## 3. Progress Story (`/topics/[id]/story`)
A generation-first build-in-public narrative.
- **Backend:** `engine/story.py` — `gather_story_facts(session, topic_id)` (deterministic: timespan, track progress, concepts by level, recent assessment deltas, calibration trend, shipped deliverables) + `build_story_prompt` + `parse_story_json` + `generate_story(session, topic_id, *, llm)`. New `routes_story.py` → `POST /api/topics/{id}/story` returning `{ headline, narrative, highlights[], facts }`. Registered in `app.py`. LLM failures already covered by existing 502 handlers.
- **Frontend:** `/topics/[id]/story` — a button to generate; renders headline + narrative paragraphs + highlight chips. Feels like the system *understands the journey*.
- Pedagogy: build-in-public, generation effect, metacognitive calibration.

## Navigation
Rail regrouped: **Daily** (Today) · **Workspace** (Dashboard, Tutor, Track, Assess, Retention, Sources) · **Reflect** (Constellation, Story).

## Verification
- `svelte-check` clean for new code; `npm run build` passes; frontend vitest green.
- Backend: unit test for `gather_story_facts` + `parse_story_json` (pure); `pytest` green.
