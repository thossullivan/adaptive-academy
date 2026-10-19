# Your first hour

A walkthrough for a new user: look around the demo topic first (no API key needed), then start
something of your own. It assumes the app is running; if it isn't, follow
[Quickstart (Docker)](../README.md#quickstart-docker) or
[Quickstart (local)](../README.md#quickstart-local) and come back.

The app is at http://localhost:8000 under Docker, or http://localhost:5173 with `just dev`.

## 1. Load the demo (no key needed)

The demo is one example topic, "Build LLMs from scratch (demo)", with about three weeks of
made-up activity: a researched reading list, a four-phase track, 15 concepts, graded
assessments, tutor conversations and the agent trace. It is built in code, so it costs nothing
and needs no key.

1. Open the app. On an empty install the home page offers **Start a program**,
   **Start a topic**, and below them **Explore a demo topic →**.
2. Click **Explore a demo topic →**. The dashboard of the demo opens. It carries a blue
   **Demo** badge, and so does its entry in the topic switcher at the top of the sidebar.

From a terminal, `just seed` adds the same demo topic (host installs only; in Docker use the
button). With no key, a **Setup needed** card on the home page and the create forms says how to
add one. Everything already recorded stays browsable.

## 2. Tour the demo

Each of these is in the left sidebar. On a phone the sidebar is behind the menu button. On a
short screen the sidebar scrolls: **Constellation**, **Teach**, **Story** and **Vault** sit
below **Sources**.

Browsing, ticking track items and rating flashcards work without a key. Anything that asks an
agent to grade, tutor or generate (submitting an assessment, a decay check or a teach-back,
sending a tutor message) needs one, and without it you get a message saying how to add it.

**Dashboard.** The overview of one topic. Look at:
- The four numbers along the top: track progress, concepts **solid**, cards due for review,
  and the mean score across probes.
- **Where you stand**: every concept with its five signals (◆ grade, ↺ held on delayed recall,
  ◷ calibrated, ◳ taught, ⚒ shipped) and its verdict. The shakiest concepts are listed first.
  Click a concept to see which signals produced its verdict and what would move it up
  ([section 5](#5-how-a-concept-earns-solid) explains the rule).
- **Calibration**: how your predicted confidence compared with your actual grade.
- **Score trajectory**, **Build progress** per phase, and **Recent agent activity** (the last
  events from the agent trace).

**Today.** The daily loop, put together from where you are: **Warm up** (decay checks and
flashcards that are due), **Build** (your next three track items), **Probe** (assess your
shakiest load-bearing concept) and **Teach back** (work through that concept with the tutor).
Each step has a button to the page that does it.

**Wayfinder.** The track as a voyage: each phase is a waypoint with its "landfall" (the thing you
ship at the end of it), "you are here" on the current phase, and your goal as the North Star.
The wind line ("cruising", "last sailed …") reflects how steadily you've been working; it
comes from your logged activity, not from your grades.

**Track.** The phases and their items. Tick items off as you do them (this needs no key).
Each phase ends in a deliverable with acceptance criteria; **⚒ Ship it for review** sends a
link or text for an artifact review. Remediation steps the Assessor added are marked
**remediation**. **Export .md** downloads the track.

**Tutor.** A Socratic tutor for one concept at a time; pick the concept at the top. The
header shows the levels it is using (**assistance**, **challenge**, set from your knowledge
estimate for that concept) and whether you've logged an attempt (**no attempt yet** /
**attempt logged**). The page always opens a fresh session, so in the demo you see the empty
state; sending a message needs a key. (The demo's two past tutor conversations are in its data,
but the app has no view of past conversations yet.)

**Assess.** Probes that make you produce an answer: **Self-explanation**, **Calibration**
(predict your confidence first), **Artifact review** and **Source quiz**. Each one writes a
graded assessment that feeds the verdicts.

**Practice.** Two kinds of deliberate practice: **Productive Failure** (attempt a novel
problem before any method is shown, then **Commit & reveal →**) and **Calibration** (lock a
confidence prediction, explain, then see the gap).

**Retention.** **Decay checks** (explain a concept from memory, graded), **Due now** flashcards
(rate them **Again / Hard / Good / Easy**; no key needed), the whole deck, and the open-ended
recall prompts.

**Sources.** The Researcher's foundation for the topic, the reading list you kept, and
**What the agents did**: the trace of every agent step for this topic (prompt versions, tool
calls, grades).

**Constellation.** The concept graph. Each star is a concept, coloured by its verdict and
sized by how load-bearing it is; lines are prerequisites. Click a star to highlight its
prerequisite chain and jump to the tutor or an assessment for it.

**Teach.** Explain a concept as if to a sharp peer; the review says what landed and what a
reader would still be confused by. A good review lights the ◳ taught signal.

**Story.** **The numbers behind the story** (progress, assessments, days active, solid
concepts) needs no key; **Compose my story** has an agent write a progress narrative from them.

**Fleet** and **Programs** (under *Voyages*) cover all your topics and long-horizon programs.
The demo has no program, so those pages stay mostly empty for now.

## 3. Add your key and start your own

1. Set `ANTHROPIC_API_KEY=sk-ant-…` in `.env` and restart the API (`just down && just up`
   for Docker, or stop and rerun `just dev`). The **Setup needed** card disappears.
2. Decide between a topic and a program:
   - **A topic** is one subject ("Build LLMs from scratch"). With the demo loaded, start one
     from the topic switcher (**＋ New topic**); on an empty install, from **Start a topic**.
     Fill in the topic, your goal (what "done" looks like), prior knowledge and time budget,
     then **Research this topic →**.
   - **A program** is a multi-month goal above topics ("PhD-level prep in custom LLMs"): go to
     **Programs → New program**, describe it, **Create program**, then on the program page
     **Run research**. Research drafts a
     milestone map with candidate topics; edit or prune it and **Accept program**. Each
     milestone then has **Start topic**, which creates its topic.
3. **Research.** The Researcher searches the web from five angles in parallel (foundational
   papers, canonical tutorials, key concepts, reference implementations, critiques), dedupes
   and ranks what it found, and writes a short foundation. It is the slowest and most
   expensive step; the form shows progress and moves you to **Sources** when it's done.
4. **Curate.** On **Sources**, untick anything that doesn't earn its place, **Save reading
   list**, then **Generate curriculum →**. Optionally **Generate quizzes** for source-grounded
   questions (they power the **Source quiz** probe).
5. **Curriculum.** The CurriculumDirector builds a phased track toward your goal, each phase
   ending in a deliverable, plus the concept graph. You land on **Track**.

## 4. The daily loop

Open **Today** and work top to bottom:

1. **Warm up**: answer the due decay checks from memory and rate the due cards.
2. **Build**: do the next track item and tick it off.
3. **Probe**: assess the concept Today names (**Assess →**). If the grade shows gaps,
   **Remediate these gaps** adds targeted steps to your track.
4. **Teach back**: work that concept through with the tutor (**Open tutor →**), or explain it
   on **Teach**.

### Why the tutor withholds the answer

The tutor's tools include `log_attempt` and `reveal_solution`. A full worked solution goes
through `reveal_solution`, and the code refuses it until an attempt is logged for that
conversation (`reveal_gate` in `src/adaptive_academy/engine/tools.py`). This is in code, not
only in the prompt, so it holds however the request is phrased. Before an attempt you get
questions and hints; once you've written a real attempt, the header turns to
**attempt logged** and the tutor can open up the worked solution.

The reason is the evidence base the app is built on: generating an answer before being shown
one (and failing productively) produces deeper learning than reading the answer first. After
each turn, **what the agent did** under the message box lists the tool calls, including any
`tool:reveal_solution:blocked`.

## 5. How a concept earns "solid"

A single grade can be gamed or lucky, so the dashboard and the Constellation combine
independent signals instead (`frontend/src/lib/competence.ts`). For each concept they look at
its latest assessment of each kind:

| Signal | Lit (supports) when | Fails when |
|---|---|---|
| ◆ grade | the latest estimate is medium or high | it is low |
| ↺ decay | a delayed recall check scored 0.45 or more | it scored lower |
| ◷ calibration | your predicted confidence was within 15 points of the grade | it was further off |
| ◳ teaching | a teach-back scored 0.45 or more | it scored lower |
| ⚒ shipping | an artifact review scored 0.45 or more | it scored lower |

The verdict, checked in this order:

- **untested**: no grade and no other signal yet.
- **shaky**: the grade is low, or any signal failed.
- **solid**: graded high **and** held on delayed recall, taught, or shipped. Calibration
  alone isn't enough.
- **verified**: graded medium or high and at least one other signal lit (calibration counts).
- **unverified**: graded, but nothing corroborates it yet.

So the way up is to come back to a concept cold (decay checks), teach it, or ship something
that uses it. Programs use the same idea for their milestone gates: a milestone passes on
delayed, unassisted recall **and** a graded artifact for its load-bearing concepts
(**Check gate** on the program page shows the per-concept reasons).

## 6. Defending what you know: roleplay and paper probe

Both live on a program's milestones and need the milestone's topic to be started:

- **Spar** generates a persona suited to the milestone (a skeptical buyer, a staff engineer
  in a design review, a thesis committee) and questions you on it; the transcript is graded
  per concept.
- **Probe a paper** takes an arXiv URL or pasted text and asks structured critical-reading
  questions for you to answer in your own words; each answer is graded per concept.

Both count as artifact evidence toward the milestone gate.

## 7. Cost and control

Every model call is recorded locally with its tokens, web searches and list-price cost. The
**Usage** page (under *Voyages*) shows today, the last 7 and 30 days and all time, broken down
by feature and by model.

From one measured run on `claude-sonnet-5-5` (2026-10-19):

| Step | Cost |
|---|---|
| One scout ranking (structured output) | $0.005 |
| One full curriculum track | $0.028 |
| One tutor turn (two model calls) | about $0.011–0.013 |
| One research angle with 2 web searches | $0.081 |

Topic research runs five angles, so it is the largest single item; tutoring and grading are
cheap per turn. The README's [cost note](../README.md#honest-note-on-cost--privacy) covers
the rest.

- **Cap it:** set `AA_DAILY_BUDGET_USD=5` (any amount) in `.env` and restart the API. Once
  today's recorded spend reaches it, new API-key calls are refused with a message saying what
  was spent. It is a soft cap: the call that crosses the limit can overshoot it. For a hard
  ceiling, also set a spend limit on the key in the Anthropic Console.
- **Use your Claude subscription instead:** set `AA_LLM_BACKEND=agent_sdk` in `.env` (host
  installs only, not Docker). Calls then go through the Claude Agent SDK, which needs Claude
  Code installed and logged in. It is slower, but there is no per-token billing; Usage shows
  the SDK's own cost estimate, and the daily limit doesn't apply.

## 8. Your data

Your whole record is one SQLite file on your machine.

- **Your data** (bottom of the sidebar): **Download backup (.db)** is a consistent snapshot
  you can restore; **Download full record (.json)** is every table as JSON, for reading or
  moving elsewhere.
- From a terminal: `just backup` and `just export` write the same files to `backups/`.
- Restoring a snapshot: see
  [Back up and restore your data](../README.md#back-up-and-restore-your-data).
- **Remove the demo** when you're done with it: open its dashboard and click **Remove demo**,
  then **Yes, remove it**. It deletes the demo topic and everything that belongs to it, and
  nothing else.
