# Wayfinder — the forward-looking celestial roadmap ("The Voyage")

**Goal:** A forward-looking companion to Constellation. Where Constellation reflects the *sky of concepts* (state, mastery, prerequisites — a web), Wayfinder charts the *voyage*: your goal as a North Star, curriculum phases as waypoint-stars on an ascending path, your current position, and the next move lit. Reflection ↔ projection; web ↔ path.

**Approved direction:** "The Voyage" layout, named **Wayfinder**, placed next to **Today** in the rail (strategic "where am I headed" beside tactical "what do I do now"). Pure frontend.

## Layout
Vertical, read bottom→top as an ascent:
- **North Star** at the very top = `topic.intent.goal` (the destination), a glowing star + the goal text.
- **Phases** stacked from last (near the star) down to first (the start line), each a waypoint-star on a central course line.
- **Trail**: segments *above* the current position are dotted/faint ("to chart"); segments at/below are solid accent ("traversed").
- **Stars**: traversed = filled accent + check; current = larger, pulsing glow ring + "you are here"; ahead = hollow/faint outline.
- Each phase **card**: number, title, est_hours, flags, item progress (done/total), and the Ship deliverable as the waypoint's **"Landfall"**. The current phase is accent-bordered and surfaces the **next step** as a lit call-to-action (→ Tutor on that step / Track).
- **Reached state**: if every phase is done, the North Star celebrates ("You've arrived").
- Subtle starfield backdrop; Observatory theme.

## Status logic
- Phase `done` iff all its items `status === 'done'`.
- `current` = first phase not fully done; phases before it = `traversed`, after = `ahead`.
- `nextItem` = first non-done item in the current phase.

## Files
- `src/lib/charts/Wayfinder.svelte` — the Voyage visualization (props: `goal`, `phases` in display order future→past, `nextItem`, `reached`, `topicId`).
- `src/routes/topics/[id]/wayfinder/+page.svelte` — loads `getCurriculum` + `getTopic` (for `intent.goal`), computes status, renders.
- `Topic` type gains `intent?` (backend `TopicOut` already returns it; frontend type just omitted it).
- Rail: add **Wayfinder** to the **Daily** group (after Today); new `wayfinder` icon.

## Verification
svelte-check clean, `npm run build` passes, all routes 200. Merge to main + push.
