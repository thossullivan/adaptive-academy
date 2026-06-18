# Wayfinding Momentum ("The Voyage") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a forgiving, game-like "wind/momentum" persistence layer — per-voyage wind derived from the event log, a cross-topic Fleet view, a sea-state Wayfinder, and an anti-guilt comeback card — that models whether the learner keeps going, kept strictly independent of competence verdicts.

**Architecture:** Wind is computed on the fly from `AgentEvent` timestamps (no new tables, no cron). A pure core (`decayed_wind`, `classify`) is wrapped by DB-reading functions (`topic_wind`, `fleet`, `comeback_move`) in `engine/momentum.py`. Three read-only API routes expose it. The frontend adds a global Fleet page, a sea-state layer on the existing Wayfinder, and a comeback card on Today, with pure helpers (`wind.ts`) TDD'd in isolation.

**Tech Stack:** Python 3.12 · FastAPI · SQLModel/SQLite · pytest · ruff · uv. Frontend: SvelteKit 2 / Svelte 5 runes / Tailwind 4 / vitest.

## Global Constraints

- Backend lint: `uv run ruff check` must pass (line length 100).
- Tests run via `uv run pytest` (backend) and `npx vitest run` (frontend, from `frontend/`).
- Wind MUST be derived only — no new SQLModel tables, no migrations, no background jobs.
- Momentum MUST NOT read or write any competence/assessment verdict, and MUST NOT be persisted.
- All engine functions take an injectable `now: datetime | None = None` (default `datetime.utcnow()`) so tests are hermetic.
- Routing convention after each task: branch → `uv run pytest` green + ruff clean → `--ff-only` merge to main → push → delete branch. Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Frontend: keep pre-existing svelte-check error count unchanged (22, all in `api.test.ts`); `npm run build` must pass.

---

### Task 1: Wind pure core — `decayed_wind` + `classify`

**Files:**
- Create: `src/adaptive_academy/engine/momentum.py`
- Test: `tests/test_momentum.py`

**Interfaces:**
- Produces: `HALF_LIFE_DAYS=3.0`, `CRUISING_VALUE=2.0`, `FADING_DAYS=4`, `BECALMED_DAYS=10`, `QUALIFYING_KINDS: set[str]`, `decayed_wind(event_times: list[datetime], now: datetime) -> float`, `classify(value: float, days_since: float | None) -> str` (returns `"cruising"|"steady"|"fading"|"becalmed"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_momentum.py
from datetime import datetime, timedelta

from adaptive_academy.engine.momentum import classify, decayed_wind

NOW = datetime(2026, 6, 17, 12, 0, 0)


def test_decayed_wind_sums_half_life_weights():
    # one event now (weight 1.0) + one 3 days ago (weight 0.5) = 1.5
    times = [NOW, NOW - timedelta(days=3)]
    assert round(decayed_wind(times, NOW), 3) == 1.5


def test_decayed_wind_empty_is_zero():
    assert decayed_wind([], NOW) == 0.0


def test_classify_states():
    assert classify(0.0, None) == "becalmed"        # never sailed
    assert classify(1.0, 12.0) == "becalmed"         # gone 12 days
    assert classify(1.0, 5.0) == "fading"            # gone 5 days
    assert classify(2.5, 0.0) == "cruising"          # rich + recent
    assert classify(1.0, 1.0) == "steady"            # recent, moderate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_momentum.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'adaptive_academy.engine.momentum'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/adaptive_academy/engine/momentum.py
"""Wayfinding momentum — derived 'wind' that models persistence (whether you keep going).

Computed on the fly from the AgentEvent log: no tables, no cron. Wind decays from timestamps, so
it falls correctly even if the app is never opened. Kept strictly independent of competence.
"""

from datetime import datetime

HALF_LIFE_DAYS = 3.0
CRUISING_VALUE = 2.0
FADING_DAYS = 4
BECALMED_DAYS = 10

# AgentEvent.kind values that count as a real learning action filling the sails. Setup events
# (research:*, curriculum:*) and view events are deliberately excluded.
QUALIFYING_KINDS: set[str] = {
    "assess:graded",
    "assess:mechanism",
    "practice:generated",
    "practice:consolidated",
    "teach:graded",
    "artifact:reviewed",
    "decay:graded",
    "calibration:logged",
}


def decayed_wind(event_times: list[datetime], now: datetime) -> float:
    total = 0.0
    for t in event_times:
        age_days = (now - t).total_seconds() / 86400.0
        if age_days < 0:
            age_days = 0.0
        total += 0.5 ** (age_days / HALF_LIFE_DAYS)
    return total


def classify(value: float, days_since: float | None) -> str:
    if days_since is None or days_since >= BECALMED_DAYS:
        return "becalmed"
    if days_since >= FADING_DAYS:
        return "fading"
    if value >= CRUISING_VALUE:
        return "cruising"
    return "steady"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_momentum.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/momentum.py tests/test_momentum.py
git commit -m "feat(momentum): wind pure core — decayed_wind + classify

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `topic_wind` + `fleet` (read from AgentEvent)

**Files:**
- Modify: `src/adaptive_academy/engine/momentum.py`
- Test: `tests/test_momentum.py`

**Interfaces:**
- Consumes: `decayed_wind`, `classify`, `QUALIFYING_KINDS` (Task 1).
- Produces: `@dataclass WindState(topic_id: int, topic_title: str, value: float, state: str, last_sailed: datetime | None, days_since: float | None)`; `topic_wind(session, topic_id, *, now=None) -> WindState`; `fleet(session, *, now=None) -> list[WindState]` (sorted attention-first: becalmed, fading, steady, cruising).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_momentum.py
from sqlmodel import Session

from adaptive_academy.engine.momentum import fleet, topic_wind
from adaptive_academy.models import AgentEvent, Topic


def _topic(session: Session, title: str) -> Topic:
    t = Topic(title=title)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def _event(session, topic_id, kind, when):
    session.add(AgentEvent(topic_id=topic_id, kind=kind, detail="", created_at=when))
    session.commit()


def test_topic_wind_counts_only_qualifying_events(session):
    t = _topic(session, "Build LLMs")
    _event(session, t.id, "assess:graded", NOW)            # qualifies
    _event(session, t.id, "research:done", NOW)            # ignored (setup)
    ws = topic_wind(session, t.id, now=NOW)
    assert ws.topic_title == "Build LLMs"
    assert round(ws.value, 3) == 1.0                       # only the one qualifying event
    assert ws.state == "steady"
    assert ws.days_since == 0.0


def test_topic_wind_becalmed_when_no_events(session):
    t = _topic(session, "Quiet topic")
    ws = topic_wind(session, t.id, now=NOW)
    assert ws.state == "becalmed" and ws.value == 0.0 and ws.last_sailed is None


def test_fleet_sorts_attention_first(session):
    from datetime import timedelta
    hot = _topic(session, "Hot")
    cold = _topic(session, "Cold")
    _event(session, hot.id, "teach:graded", NOW)                       # cruising-ish/steady
    _event(session, cold.id, "assess:graded", NOW - timedelta(days=12))  # becalmed
    order = [w.topic_title for w in fleet(session, now=NOW)]
    assert order[0] == "Cold"  # becalmed floats to the top
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_momentum.py -q`
Expected: FAIL — `ImportError: cannot import name 'topic_wind'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/adaptive_academy/engine/momentum.py
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.models import AgentEvent, Topic

# (keep the existing `from datetime import datetime` at top)

_ATTENTION_ORDER = {"becalmed": 0, "fading": 1, "steady": 2, "cruising": 3}


@dataclass
class WindState:
    topic_id: int
    topic_title: str
    value: float
    state: str
    last_sailed: datetime | None
    days_since: float | None


def _utcnow() -> datetime:
    return datetime.utcnow()


def topic_wind(session: Session, topic_id: int, *, now: datetime | None = None) -> WindState:
    now = now or _utcnow()
    topic = session.get(Topic, topic_id)
    title = topic.title if topic else ""
    times = [
        e.created_at
        for e in session.exec(
            select(AgentEvent).where(AgentEvent.topic_id == topic_id)).all()
        if e.kind in QUALIFYING_KINDS
    ]
    value = decayed_wind(times, now)
    last = max(times) if times else None
    days_since = (now - last).total_seconds() / 86400.0 if last else None
    return WindState(topic_id, title, round(value, 4), classify(value, days_since), last, days_since)


def fleet(session: Session, *, now: datetime | None = None) -> list[WindState]:
    now = now or _utcnow()
    topics = session.exec(select(Topic)).all()
    states = [topic_wind(session, t.id, now=now) for t in topics]
    states.sort(key=lambda w: (_ATTENTION_ORDER.get(w.state, 9), -(w.value)))
    return states
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_momentum.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/momentum.py tests/test_momentum.py
git commit -m "feat(momentum): topic_wind + fleet from the event log

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `comeback_move` (the C-shaped seam)

**Files:**
- Modify: `src/adaptive_academy/engine/momentum.py`
- Test: `tests/test_momentum.py`

**Interfaces:**
- Consumes: `topic_wind`, `WindState` (Task 2).
- Produces: `@dataclass ComebackMove(kind: str, label: str, href: str, minutes: int)`; `comeback_move(session, topic_id, *, now=None) -> ComebackMove | None`. Returns `None` when the voyage is healthy (cruising/steady). Otherwise: the next undone curriculum `Item` (earliest phase by position, then item by position, first with `status != "done"`), else a self-explanation fallback. **This function is the seam** — v1 reads only events/curriculum; a future version could add stored state without changing the signature.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_momentum.py
from datetime import timedelta

from adaptive_academy.engine.momentum import comeback_move
from adaptive_academy.models import Item, Phase, Track


def test_comeback_move_none_when_healthy(session):
    t = _topic(session, "Healthy")
    _event(session, t.id, "assess:graded", NOW)  # steady
    assert comeback_move(session, t.id, now=NOW) is None


def test_comeback_move_picks_next_undone_item_when_fading(session):
    t = _topic(session, "Fading topic")
    _event(session, t.id, "assess:graded", NOW - timedelta(days=5))  # fading
    track = Track(topic_id=t.id, title="tr")
    session.add(track)
    session.commit()
    session.refresh(track)
    phase = Phase(track_id=track.id, title="P1", position=0)
    session.add(phase)
    session.commit()
    session.refresh(phase)
    session.add(Item(phase_id=phase.id, text="done item", type="read", position=0, status="done"))
    session.add(Item(phase_id=phase.id, text="derive the gradient", type="write", position=1,
                     status="todo"))
    session.commit()
    move = comeback_move(session, t.id, now=NOW)
    assert move is not None
    assert move.label == "derive the gradient"
    assert move.href == f"/topics/{t.id}/track"


def test_comeback_move_falls_back_without_track(session):
    t = _topic(session, "No track")
    _event(session, t.id, "assess:graded", NOW - timedelta(days=12))  # becalmed
    move = comeback_move(session, t.id, now=NOW)
    assert move is not None and move.kind == "self_explain"
    assert move.href == f"/topics/{t.id}/assess"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_momentum.py -q`
Expected: FAIL — `ImportError: cannot import name 'comeback_move'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/adaptive_academy/engine/momentum.py
from adaptive_academy.models import Item, Phase, Track  # extend the models import line


@dataclass
class ComebackMove:
    kind: str
    label: str
    href: str
    minutes: int


def comeback_move(
    session: Session, topic_id: int, *, now: datetime | None = None
) -> ComebackMove | None:
    ws = topic_wind(session, topic_id, now=now)
    if ws.state not in ("fading", "becalmed"):
        return None
    track = session.exec(select(Track).where(Track.topic_id == topic_id)).first()
    if track is not None:
        phases = session.exec(
            select(Phase).where(Phase.track_id == track.id).order_by(Phase.position)).all()
        for p in phases:
            items = session.exec(
                select(Item).where(Item.phase_id == p.id).order_by(Item.position)).all()
            for it in items:
                if it.status != "done":
                    return ComebackMove(
                        kind=it.type, label=it.text[:120],
                        href=f"/topics/{topic_id}/track", minutes=25)
    return ComebackMove(
        kind="self_explain",
        label="Do a quick self-explanation on a load-bearing concept",
        href=f"/topics/{topic_id}/assess", minutes=15)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_momentum.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/momentum.py tests/test_momentum.py
git commit -m "feat(momentum): comeback_move (the C-shaped seam)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: API routes — `/api/fleet`, `/api/topics/{id}/wind`, `/api/topics/{id}/comeback`

**Files:**
- Modify: `src/adaptive_academy/api/schemas.py` (append)
- Create: `src/adaptive_academy/api/routes_momentum.py`
- Modify: `src/adaptive_academy/api/app.py` (import + register)
- Test: `tests/test_api_momentum.py`

**Interfaces:**
- Consumes: `fleet`, `topic_wind`, `comeback_move` (Tasks 2–3); `get_session` (existing dep).
- Produces (response shapes): `WindStateOut{topic_id:int, topic_title:str, value:float, state:str, last_sailed:str|None, days_since:float|None}`; `ComebackMoveOut{kind:str, label:str, href:str, minutes:int}`; `ComebackOut{move: ComebackMoveOut | None}`. Routes: `GET /api/fleet -> list[WindStateOut]`, `GET /api/topics/{id}/wind -> WindStateOut`, `GET /api/topics/{id}/comeback -> ComebackOut`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_momentum.py
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import AgentEvent, Topic


def test_fleet_wind_and_comeback_endpoints(session):
    app.dependency_overrides[get_session] = lambda: session
    t = Topic(title="Build LLMs")
    session.add(t)
    session.commit()
    session.refresh(t)
    # one qualifying event 12 days ago -> becalmed
    session.add(AgentEvent(topic_id=t.id, kind="assess:graded", detail="",
                           created_at=datetime.utcnow() - timedelta(days=12)))
    session.commit()

    client = TestClient(app)

    fleet = client.get("/api/fleet")
    assert fleet.status_code == 200
    assert fleet.json()[0]["topic_title"] == "Build LLMs"

    wind = client.get(f"/api/topics/{t.id}/wind")
    assert wind.status_code == 200 and wind.json()["state"] == "becalmed"

    cb = client.get(f"/api/topics/{t.id}/comeback")
    assert cb.status_code == 200 and cb.json()["move"] is not None
    assert cb.json()["move"]["kind"] == "self_explain"
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api_momentum.py -q`
Expected: FAIL — 404s (routes not registered)

- [ ] **Step 3a: Append schemas**

```python
# append to src/adaptive_academy/api/schemas.py
class WindStateOut(BaseModel):
    topic_id: int
    topic_title: str
    value: float
    state: str
    last_sailed: Optional[str] = None
    days_since: Optional[float] = None


class ComebackMoveOut(BaseModel):
    kind: str
    label: str
    href: str
    minutes: int


class ComebackOut(BaseModel):
    move: Optional[ComebackMoveOut] = None
```

- [ ] **Step 3b: Create the router**

```python
# src/adaptive_academy/api/routes_momentum.py
"""Read-only momentum routes — derived wind, the Fleet, and the comeback move."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import ComebackMoveOut, ComebackOut, WindStateOut
from adaptive_academy.engine.momentum import comeback_move, fleet, topic_wind

router = APIRouter(prefix="/api", tags=["momentum"])


def _wind_out(ws) -> WindStateOut:
    return WindStateOut(
        topic_id=ws.topic_id, topic_title=ws.topic_title, value=ws.value, state=ws.state,
        last_sailed=ws.last_sailed.isoformat() if ws.last_sailed else None,
        days_since=round(ws.days_since, 2) if ws.days_since is not None else None)


@router.get("/fleet", response_model=list[WindStateOut])
def get_fleet(session: Session = Depends(get_session)) -> list[WindStateOut]:
    return [_wind_out(w) for w in fleet(session)]


@router.get("/topics/{topic_id}/wind", response_model=WindStateOut)
def get_wind(topic_id: int, session: Session = Depends(get_session)) -> WindStateOut:
    return _wind_out(topic_wind(session, topic_id))


@router.get("/topics/{topic_id}/comeback", response_model=ComebackOut)
def get_comeback(topic_id: int, session: Session = Depends(get_session)) -> ComebackOut:
    m = comeback_move(session, topic_id)
    move = ComebackMoveOut(kind=m.kind, label=m.label, href=m.href, minutes=m.minutes) if m else None
    return ComebackOut(move=move)
```

- [ ] **Step 3c: Register in app.py**

In `src/adaptive_academy/api/app.py`, add `routes_momentum` to the `from adaptive_academy.api import (...)` block, and add this line next to the other `app.include_router(...)` calls:

```python
    app.include_router(routes_momentum.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api_momentum.py -q && uv run ruff check src/adaptive_academy/`
Expected: PASS (1 test) + ruff clean

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/api/schemas.py src/adaptive_academy/api/routes_momentum.py src/adaptive_academy/api/app.py tests/test_api_momentum.py
git commit -m "feat(api): momentum routes — fleet, wind, comeback

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Frontend pure helpers + api client

**Files:**
- Create: `frontend/src/lib/wind.ts`
- Create: `frontend/src/lib/wind.test.ts`
- Modify: `frontend/src/lib/types.ts` (append)
- Modify: `frontend/src/lib/api.ts` (import + methods)

**Interfaces:**
- Produces: `STATE_LABEL`, `STATE_COLOR` (Record<string,string>), `seaIntensity(state) -> number` (0..1 for animation strength), `comebackTone(state) -> 'playful' | 'warm' | null`; types `WindState`, `ComebackMove`, `Comeback`; api methods `getFleet()`, `getWind(topicId)`, `getComeback(topicId)`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/wind.test.ts
import { describe, expect, it } from 'vitest';
import { comebackTone, seaIntensity } from './wind';

describe('wind helpers', () => {
  it('comebackTone: playful for a short fade, warm for a heavy becalming, null when healthy', () => {
    expect(comebackTone('fading')).toBe('playful');
    expect(comebackTone('becalmed')).toBe('warm');
    expect(comebackTone('steady')).toBeNull();
    expect(comebackTone('cruising')).toBeNull();
  });

  it('seaIntensity rises with momentum and is flat when becalmed', () => {
    expect(seaIntensity('becalmed')).toBe(0);
    expect(seaIntensity('cruising')).toBeGreaterThan(seaIntensity('steady'));
    expect(seaIntensity('steady')).toBeGreaterThan(seaIntensity('fading'));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/lib/wind.test.ts`
Expected: FAIL — cannot find module `./wind`

- [ ] **Step 3a: Create the helper**

```ts
// frontend/src/lib/wind.ts
export type WindStateName = 'cruising' | 'steady' | 'fading' | 'becalmed';

export const STATE_LABEL: Record<string, string> = {
  cruising: 'Cruising',
  steady: 'Steady',
  fading: 'Fading',
  becalmed: 'Becalmed'
};

export const STATE_COLOR: Record<string, string> = {
  cruising: 'var(--success)',
  steady: 'var(--accent)',
  fading: 'var(--accent)',
  becalmed: 'var(--danger)'
};

// 0 = flat/still water (becalmed), 1 = lively seas (cruising). Drives sea-state animation strength.
const INTENSITY: Record<string, number> = { becalmed: 0, fading: 0.3, steady: 0.65, cruising: 1 };
export function seaIntensity(state: string): number {
  return INTENSITY[state] ?? 0;
}

// Adaptive tone: a short fade gets the playful voice; a heavy becalming gets the warm, gentle one.
export function comebackTone(state: string): 'playful' | 'warm' | null {
  if (state === 'fading') return 'playful';
  if (state === 'becalmed') return 'warm';
  return null;
}
```

- [ ] **Step 3b: Append types**

```ts
// append to frontend/src/lib/types.ts
export interface WindState {
  topic_id: number;
  topic_title: string;
  value: number;
  state: string;
  last_sailed: string | null;
  days_since: number | null;
}
export interface ComebackMove {
  kind: string;
  label: string;
  href: string;
  minutes: number;
}
export interface Comeback {
  move: ComebackMove | null;
}
```

- [ ] **Step 3c: Add api methods**

In `frontend/src/lib/api.ts`, add `WindState, Comeback` to the type import from `./types`, and add these methods inside the `api` object (before the closing `};`):

```ts
  getFleet: () => fetch('/api/fleet').then(j<WindState[]>),
  getWind: (topicId: number) => fetch(`/api/topics/${topicId}/wind`).then(j<WindState>),
  getComeback: (topicId: number) => fetch(`/api/topics/${topicId}/comeback`).then(j<Comeback>),
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npx vitest run src/lib/wind.test.ts`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/wind.ts frontend/src/lib/wind.test.ts frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(wind): frontend pure helpers + api client

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Fleet page + global Rail entry

**Files:**
- Create: `frontend/src/routes/fleet/+page.svelte`
- Modify: `frontend/src/lib/shell/Rail.svelte` (add a global section)
- Modify: `frontend/src/lib/shell/Icon.svelte` (add a `fleet` icon)

**Interfaces:**
- Consumes: `api.getFleet`, `WindState` (Task 5); `STATE_LABEL`, `STATE_COLOR`, `seaIntensity` (Task 5).
- Produces: route `/fleet`.

- [ ] **Step 1: Add the `fleet` icon**

In `frontend/src/lib/shell/Icon.svelte`, add to the `paths` record:

```js
    fleet: 'M3 17h18M5 17l2-6h10l2 6M9 11V6h6v5M11 6V3h2v3'
```

- [ ] **Step 2: Add a global Rail section**

In `frontend/src/lib/shell/Rail.svelte`, the `sections` array is gated on `tid == null`. Add a top-level **Voyages** group that is ALWAYS shown (even with no topic). Change the `$derived` so it prepends this group regardless of `tid`:

```svelte
  const sections = $derived<Section[]>([
    {
      label: 'Voyages',
      items: [{ label: 'Fleet', icon: 'fleet', href: '/fleet', match: (p) => p === '/fleet' }]
    },
    ...(tid == null ? [] : [
      // ...existing Daily / Workspace / Reflect / Connections groups unchanged...
    ])
  ]);
```

(Keep the existing Daily/Workspace/Reflect/Connections group objects exactly as they are — just move them inside the spread.)

- [ ] **Step 3: Create the Fleet page**

```svelte
<!-- frontend/src/routes/fleet/+page.svelte -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { WindState } from '$lib/types';
  import { STATE_LABEL, STATE_COLOR, seaIntensity } from '$lib/wind';
  import Page from '$lib/shell/Page.svelte';
  import { Card } from '$lib/ui';

  let fleet = $state<WindState[]>([]);
  let loading = $state(true);
  let panorama = $state(true); // hero panorama vs. collapsed sea-tiles

  onMount(async () => {
    try {
      fleet = await api.getFleet();
    } finally {
      loading = false;
    }
  });
</script>

<Page eyebrow="Voyages" title="The Fleet" lead="Your whole learning life at a glance. Becalmed voyages need wind; cruising ones just hum along.">
  {#snippet actions()}
    <button class="eyebrow transition-colors hover:text-fg" onclick={() => (panorama = !panorama)}>
      {panorama ? 'Collapse to tiles' : 'Show harbor'}
    </button>
  {/snippet}

  {#if loading}
    <p class="py-10 text-center text-sm text-faint">Charting the seas…</p>
  {:else if !fleet.length}
    <p class="py-10 text-center text-sm text-faint">No voyages yet. Create a topic to set sail.</p>
  {:else if panorama}
    <!-- Hero: one shared ocean; ship height = momentum -->
    <div class="relative h-[420px] overflow-hidden rounded-[var(--radius)] border border-border"
         style="background:radial-gradient(120% 90% at 50% -10%, color-mix(in oklab,var(--accent) 8%, var(--surface)) 0%, var(--bg) 70%)">
      <div class="absolute left-1/2 top-3 -translate-x-1/2 text-center">
        <div class="text-2xl">⭐</div><div class="eyebrow">North Star</div>
      </div>
      {#each fleet as w, i (w.topic_id)}
        <a href={`/topics/${w.topic_id}/wayfinder`}
           class="absolute flex flex-col items-center transition-transform hover:scale-110"
           style={`left:${8 + (i * 84) % 84 + (i % 5) * 16}%; bottom:${10 + seaIntensity(w.state) * 62}%; opacity:${0.45 + seaIntensity(w.state) * 0.55}`}>
          <span class="text-xl">⛵</span>
          <span class="eyebrow whitespace-nowrap" style:color={STATE_COLOR[w.state]}>{w.topic_title}</span>
        </a>
      {/each}
      <div class="absolute inset-x-0 bottom-0 h-16"
           style="background:linear-gradient(180deg, transparent, color-mix(in oklab, var(--bg) 70%, transparent))"></div>
    </div>
  {:else}
    <!-- Collapsed sea-tiles: becalmed first (already sorted by the API) -->
    <div class="flex flex-col gap-2">
      {#each fleet as w (w.topic_id)}
        <a href={`/topics/${w.topic_id}/wayfinder`} class="block">
          <Card pad class="transition-colors hover:border-accent">
            <div class="flex items-center gap-3">
              <span class="text-lg" style:opacity={0.4 + seaIntensity(w.state) * 0.6}>⛵</span>
              <span class="flex-1 truncate text-sm text-fg-dim">{w.topic_title}</span>
              {#if w.days_since != null}
                <span class="eyebrow text-faint">{Math.round(w.days_since)}d</span>
              {/if}
              <span class="eyebrow w-20 text-right" style:color={STATE_COLOR[w.state]}>{STATE_LABEL[w.state]}</span>
            </div>
          </Card>
        </a>
      {/each}
    </div>
  {/if}
</Page>
```

- [ ] **Step 4: Verify build + check**

Run (from `frontend/`): `npm run build && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | grep COMPLETED`
Expected: build succeeds; svelte-check still reports `22 ERRORS` (unchanged — all pre-existing in `api.test.ts`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/fleet frontend/src/lib/shell/Rail.svelte frontend/src/lib/shell/Icon.svelte
git commit -m "feat(fleet): Fleet page (harbor panorama + sea-tiles) and global rail entry

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Wayfinder sea-state layer

**Files:**
- Modify: `frontend/src/routes/topics/[id]/wayfinder/+page.svelte`

**Interfaces:**
- Consumes: `api.getWind`, `WindState` (Task 5); `seaIntensity`, `STATE_LABEL`, `STATE_COLOR` (Task 5).
- Produces: a momentum chip + a sea-state atmosphere band on the Wayfinder, gated by `prefers-reduced-motion`.

- [ ] **Step 1: Load wind in the page script**

In the wayfinder page's `<script>`, add the import and state, and fetch wind in `onMount` alongside the existing data load:

```ts
  import { seaIntensity, STATE_LABEL, STATE_COLOR } from '$lib/wind';
  import type { WindState } from '$lib/types';
  let wind = $state<WindState | null>(null);
  // inside the existing onMount, after the current load:
  wind = await api.getWind(topicId).catch(() => null);
```

- [ ] **Step 2: Add the momentum chip + sea band markup**

Near the top of the page's template (just under the page header), add:

```svelte
{#if wind}
  <div class="mb-4 flex items-center gap-2">
    <span class="eyebrow" style:color={STATE_COLOR[wind.state]}>⛵ {STATE_LABEL[wind.state]}</span>
    {#if wind.days_since != null}<span class="eyebrow text-faint">· last sailed {Math.round(wind.days_since)}d ago</span>{/if}
  </div>
  <div class="sea pointer-events-none" style={`--swell:${seaIntensity(wind.state)}`} aria-hidden="true">
    <div class="wave"></div><div class="wave wave2"></div>
  </div>
{/if}
```

- [ ] **Step 3: Add the scoped styles (reduced-motion aware)**

Add to the page's `<style>` block (create one if absent):

```css
  .sea { position: relative; height: calc(8px + var(--swell) * 22px); opacity: calc(0.25 + var(--swell) * 0.6); margin-bottom: 1rem; }
  .wave { position: absolute; inset: 0; background: repeating-linear-gradient(90deg, transparent, transparent 18px, color-mix(in oklab, var(--accent) 30%, transparent) 19px, transparent 20px); animation: drift calc(6s - var(--swell) * 3s) linear infinite; }
  .wave2 { opacity: 0.5; animation-duration: calc(9s - var(--swell) * 3s); }
  @keyframes drift { to { transform: translateX(-40px); } }
  @media (prefers-reduced-motion: reduce) { .wave { animation: none; } }
```

- [ ] **Step 4: Verify build + check**

Run (from `frontend/`): `npm run build && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | grep COMPLETED`
Expected: build succeeds; svelte-check still `22 ERRORS` (unchanged).

- [ ] **Step 5: Commit**

```bash
git add "frontend/src/routes/topics/[id]/wayfinder/+page.svelte"
git commit -m "feat(wayfinder): sea-state momentum layer (reduced-motion aware)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Today comeback card (adaptive tone)

**Files:**
- Create: `frontend/src/lib/ui/ComebackCard.svelte`
- Modify: `frontend/src/lib/ui/index.ts` (export it)
- Modify: `frontend/src/routes/topics/[id]/today/+page.svelte` (load wind+comeback, render the card)

**Interfaces:**
- Consumes: `api.getWind`, `api.getComeback`, `WindState`, `Comeback` (Task 5); `comebackTone`, `STATE_LABEL` (Task 5).
- Produces: `<ComebackCard wind={WindState} comeback={Comeback} />`.

- [ ] **Step 1: Create the card component**

```svelte
<!-- frontend/src/lib/ui/ComebackCard.svelte -->
<script lang="ts">
  import type { WindState, Comeback } from '$lib/types';
  import { comebackTone } from '$lib/wind';
  import Card from './Card.svelte';
  import Button from './Button.svelte';

  let { wind, comeback }: { wind: WindState; comeback: Comeback } = $props();
  const tone = $derived(comebackTone(wind.state));
  const days = $derived(wind.days_since != null ? Math.round(wind.days_since) : 0);
</script>

{#if tone && comeback.move}
  <Card class="rise" eyebrow={tone === 'warm' ? '⚑ Becalmed' : '⛵ Catching a breeze'}>
    {#if tone === 'warm'}
      <h3 class="font-display text-lg text-fg">Your voyage is waiting.</h3>
      <p class="mt-1 text-sm text-muted">It's been {days} days — no matter. One good move catches the wind again.</p>
    {:else}
      <h3 class="font-display text-lg text-fg">A breeze on the horizon.</h3>
      <p class="mt-1 text-sm text-muted">The sails are stirring after {days} days. Take the helm and you're moving.</p>
    {/if}
    <div class="my-3 rounded-[var(--radius-sm)] border border-border bg-bg-soft/40 px-3 py-2">
      <div class="eyebrow text-faint">Your one move · ~{comeback.move.minutes} min</div>
      <div class="mt-1 text-sm text-fg-dim">{comeback.move.label}</div>
    </div>
    <Button size="sm" href={comeback.move.href}>
      {tone === 'warm' ? '⛵ Catch the wind' : '⛵ Set sail'}
    </Button>
  </Card>
{/if}
```

- [ ] **Step 2: Export it**

Append to `frontend/src/lib/ui/index.ts`:

```ts
export { default as ComebackCard } from './ComebackCard.svelte';
```

- [ ] **Step 3: Render on Today**

In `frontend/src/routes/topics/[id]/today/+page.svelte` `<script>`, add:

```ts
  import { ComebackCard } from '$lib/ui';
  import type { WindState, Comeback } from '$lib/types';
  let wind = $state<WindState | null>(null);
  let comeback = $state<Comeback | null>(null);
  // inside the existing onMount:
  wind = await api.getWind(topicId).catch(() => null);
  comeback = await api.getComeback(topicId).catch(() => null);
```

And near the top of the Today template (above the existing content):

```svelte
{#if wind && comeback}
  <div class="mb-5"><ComebackCard {wind} {comeback} /></div>
{/if}
```

- [ ] **Step 4: Verify build + check + vitest**

Run (from `frontend/`): `npx vitest run && npm run build && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | grep COMPLETED`
Expected: vitest all pass (incl. Task 5's 2 wind tests); build succeeds; svelte-check still `22 ERRORS` (unchanged).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/ui/ComebackCard.svelte frontend/src/lib/ui/index.ts "frontend/src/routes/topics/[id]/today/+page.svelte"
git commit -m "feat(today): adaptive-tone comeback card

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **Verify `QUALIFYING_KINDS` against the live event log before shipping Task 1.** Run `sqlite3 adaptive_academy.db "SELECT DISTINCT kind FROM agentevent ORDER BY 1;"` and confirm the real "learning action" kinds match this set (e.g. the grade engine may emit `assess:graded` under a slightly different string). Adjust the set to the actual kinds; the tests use representative members, so update them together. This is the one place the plan touches reality that the tests can't fully pin.
- **`AgentEvent.created_at`** is naive UTC; keep `now` naive (the engine uses `datetime.utcnow()`).
- Momentum is read-only and additive — no existing route, table, or competence path changes.
- After all tasks, do a final full-suite pass: `uv run pytest -q` and (from `frontend/`) `npx vitest run && npm run build`.

## Out of scope (deferred, per the design)
Gems/currency, push notifications/cron, per-action-type weighting, stored comeback state (the seam is ready), comeback decay-check prioritization (v1 uses the next undone curriculum item).
