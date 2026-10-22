# Your first hour

A walkthrough for new users. Look around the demo topic first (no API key needed), then start
something of your own. This assumes the app is running. If it isn't, follow
[Get started](../README.md#get-started) and come back.

The app is at http://localhost:8000 with Docker, or http://localhost:5173 with `just dev`.

## 1. Load the demo (no key needed)

The demo is one example topic, "Build LLMs from scratch (demo)", with about three weeks of
made-up activity: a reading list, a four-phase track, 15 concepts, graded assessments, tutor
conversations, and the agent log. It's built in code, so it costs nothing and needs no key.

1. Open the app. On a fresh install the home page shows **Start a program**,
   **Start a topic**, and below them **Explore a demo topic →**.
2. Click **Explore a demo topic →**. The demo's dashboard opens. It has a blue **Demo** badge,
   and so does its entry in the topic switcher at the top of the sidebar.

Without Docker, `just seed` adds the same demo from a terminal. In Docker, use the button.
Until you add a key, a **Setup needed** card on the home page and the create forms tells you
how. Everything already recorded can still be browsed.

## 2. Tour the demo

Everything below is in the left sidebar. On a phone, the sidebar is behind the menu button.
Under the topic switcher it starts with **Today** and **Dashboard**, then three groups:
*Learn* (Tutor, Practice, Assess, Teach), *Map & progress* (Track, Wayfinder, Constellation,
Retention), and *Library* (Sources, Vault, Story). Then comes *All topics* (Fleet, Programs).
**Usage** and **Your data** are at the bottom.

You can browse, tick off track items, and rate flashcards without a key. Anything that asks an
agent to grade, tutor, or write something needs one: submitting an assessment, a decay check,
or a teach-back, or sending a tutor message. Without a key, you get a message saying how to
add it.

**Dashboard.** The overview of one topic. Look at:
- The four numbers along the top: track progress, concepts **solid**, cards due for review,
  and your average score.
- **Where you stand**: every concept with its five signals (◆ grade, ↺ held on delayed recall,
  ◷ calibrated, ◳ taught, ⚒ shipped) and its verdict. The weakest concepts come first. Click
  a concept to see what its verdict is based on and what would raise it
  ([section 5](#5-how-a-concept-earns-solid) explains the rule).
- **Calibration**: how sure you said you were, compared with the grade you got.
- **Score trajectory**, **Build progress** per phase, and **Recent agent activity** (the
  latest entries from the agent log).

**Today.** What to do next, based on where you are. **Warm up** (decay checks and flashcards
that are due), **Build** (your next three track items), **Probe** (test your weakest important
concept), and **Teach back** (work through that concept with the tutor). Each step has a
button to the right page.

**Wayfinder.** Your track drawn as a voyage. Each phase is a stop with its "landfall" (what you
ship at the end of it), "you are here" marks the current phase, and your goal is the North
Star. The wind line ("cruising", "last sailed …") shows how steadily you've been working. It
comes from your activity, not your grades.

**Track.** The phases and their items. Tick items off as you go (no key needed). Each phase
ends with something to build, with criteria for when it's done. **⚒ Ship it for review** sends
a link or some text to be reviewed. Steps the Assessor added to fill gaps are marked
**remediation**. **Export .md** downloads the track.

**Tutor.** A tutor that works through one concept with you by asking questions. Pick the
concept at the top. The header shows how much help it's giving (**assistance**), how hard it's
pushing (**challenge**), and whether you've made an attempt yet (**no attempt yet** /
**attempt logged**). The page always opens a new session, so in the demo it starts empty.
Sending a message needs a key. Nothing is saved until you send something.

**Assess.** Tests where you have to produce the answer yourself: **Self-explanation**,
**Calibration** (say how sure you are first), **Artifact review**, and **Source quiz**. Each
one is saved and feeds the verdicts. Self-explanation, calibration, and the source quiz set the
concept's ◆ grade. An artifact review lights the ⚒ shipped signal but doesn't touch the grade,
so one review can't count twice.

**Practice.** Two kinds of practice. **Productive Failure**: try a new problem before you're
shown how, then **Commit & reveal →**. **Calibration**: lock in how sure you are, explain, then
see how far off you were.

**Retention.** **Decay checks** (explain a concept from memory, graded), **Due now**
flashcards (rate them **Again / Hard / Good / Easy**, no key needed), the whole deck, and
open-ended recall prompts.

**Sources.** The Researcher's summary of the topic, the reading list you kept, and **What the
agents did**: a log of every agent step for this topic (prompt versions, tool calls, grades).

**Constellation.** The concept graph. Each star is a concept, coloured by its verdict and sized
by how much else depends on it. Lines show prerequisites. Click a star to highlight what it
depends on, and jump to the tutor or a test for it.

**Teach.** Explain a concept as if to a smart friend. The review says what came across and
what would still confuse a reader. A good review lights the ◳ taught signal.

**Story.** **The numbers behind the story** (progress, assessments, days active, and concepts
graded high, plus how many have no grade yet) works without a key. **Compose my story** has an
agent write up your progress from those numbers. A concept with no grade counts as untested
here, never as solid. (On this page "solid" just means graded high. The dashboard's "concepts
solid" uses the stricter rule from [section 5](#5-how-a-concept-earns-solid).)

**Fleet** and **Programs** (under *All topics*) cover all your topics and longer programs. The
demo has no program, so those pages are mostly empty for now.

## 3. Add your key and start your own

1. Set `ANTHROPIC_API_KEY=sk-ant-…` in `.env` and restart (`just down && just up` with
   Docker, or stop and rerun `just dev`). The **Setup needed** card goes away.
2. Choose a topic or a program:
   - **A topic** is one subject, like "Build LLMs from scratch". With the demo loaded, start
     one from the topic switcher (**＋ New topic**). On a fresh install, use
     **Start a topic**. Fill in the topic, your goal (what "done" looks like), what you
     already know, and how much time you have. Then click **Research this topic →**.
   - **A program** is a bigger goal made of several topics, like "PhD-level prep in custom
     LLMs". Go to **Programs → New program**, describe it, click **Create program**, then
     **Run research** on the program page. Research drafts a set of milestones with suggested
     topics. Edit or trim it, then click **Accept program**. Each milestone then has a
     **Start topic** button.
3. **Research.** The Researcher searches the web from five angles at once (key papers,
   tutorials, core concepts, reference code, critiques), removes duplicates, ranks what it
   found, and writes a short summary. This is the slowest and most expensive step. The form
   shows progress and takes you to **Sources** when it's done.
4. **Curate.** On **Sources**, untick anything you don't want, click **Save reading list**, then
   **Generate curriculum →**. You can also click **Generate quizzes** to make questions from
   the sources (these feed the **Source quiz**).
5. **Curriculum.** The CurriculumDirector builds a track toward your goal in phases, each
   ending with something to build, plus the concept graph. You land on **Track**.

## 4. The daily loop

Open **Today** and work from top to bottom:

1. **Warm up**: answer the due decay checks from memory and rate the due cards.
2. **Build**: do the next track item and tick it off.
3. **Probe**: test the concept Today names (**Assess →**). If the grade shows gaps,
   **Remediate these gaps** adds steps to your track to fill them.
4. **Teach back**: work through that concept with the tutor (**Open tutor →**), or explain it
   on **Teach**.

### Why the tutor holds back the answer

The tutor has two tools, `log_attempt` and `reveal_solution`. A full worked solution can only
come through `reveal_solution`, and the code blocks it until you've made an attempt in that
conversation (`reveal_gate` in `src/adaptive_academy/engine/tools.py`). Because this is in the
code and not just the prompt, it holds no matter how you ask. Before you try, you get
questions and hints. Once you've written a real attempt, the header changes to
**attempt logged** and the tutor can show the full solution.

The tutor could still write the answer in an ordinary reply, so every reply before an
attempt is checked too (`engine/solution_guard.py`). A second, cheap model call reads the
draft and asks: does this hand over the answer, or only ask and hint? If it gives the answer
away, you never see it: the tutor is asked once more for a question or a hint, and if that
also gives it away, you get a fixed prompt to share your first step instead.

The research behind the app says that trying to answer before you're shown how (even if you
get it wrong) leads to deeper learning than reading the answer first. After each turn,
**what the agent did** under the message box lists the tool calls, including any
`tool:reveal_solution:blocked`.

## 5. How a concept earns "solid"

One grade can be lucky, or gamed. So the dashboard and the Constellation look at several
separate signals instead (`frontend/src/lib/competence.ts`). For each concept, they use the
latest result of each kind:

| Signal | Counts for you when | Counts against you when |
|---|---|---|
| ◆ grade | the concept's estimate is medium or high | it is low |
| ↺ decay | a delayed recall check scored 0.45 or more | it scored lower |
| ◷ calibration | how sure you said you were was within 15 points of your grade | it was further off |
| ◳ teaching | a teach-back scored 0.45 or more | it scored lower |
| ⚒ shipping | an artifact review scored 0.45 or more | it scored lower |

How a single answer is graded: each concept has a short rubric with the key ideas an answer
must cover and the common misconceptions. The grader reads your answer, judges each key idea
by meaning (any wording or notation counts), and names the ones you missed and any
misconception you actually committed (quoting one to reject it doesn't count). The code then
caps the score: at most 0.70 if a key idea is missing, at most 0.50 for a misconception.

The grade is the estimate the Assessor saves when it grades one of these: a self-explanation,
calibration, or source quiz, a decay check, a roleplay, or a paper probe. A new concept gets a
placeholder estimate from the curriculum. Teaching, productive failure, and artifact reviews
never change the grade. So until one of the graded tests above exists, the concept has
**no grade**, whatever the placeholder says.

The verdict, checked in this order:

- **untested**: no grade and no other signal yet.
- **shaky**: the grade is low, or any signal counts against it.
- **solid**: graded high **and** held up on delayed recall, taught, or shipped. Calibration on
  its own isn't enough.
- **verified**: graded medium or high, plus at least one other signal for it (calibration
  counts here).
- **unverified**: everything else. Either it's graded medium or high with nothing backing it
  up yet, or a signal counts for it (taught or shipped, say) but there's no grade yet.

So to move a concept up, come back to it cold (decay checks), teach it, or build something
with it. Programs use the same idea for milestones. A milestone passes when its important
concepts hold up on delayed recall without help **and** have a graded artifact. **Check gate**
on the program page shows the reasons for each concept.

## 6. Defending what you know: roleplay and paper probe

Both are on a program's milestones, and the milestone's topic has to be started first.

- **Spar** creates a character that fits the milestone (a skeptical buyer, a staff engineer in
  a design review, a thesis committee) who questions you. The conversation is graded per
  concept.
- **Probe a paper** takes an arXiv link or pasted text and asks you questions about it to
  answer in your own words. Each answer is graded per concept.

Both count as artifact evidence for the milestone.

## 7. Cost and control

Every AI call is recorded on your machine with its tokens, web searches, and cost at list
price. The **Usage** page (bottom of the sidebar) shows today, the last 7 and 30 days, and all
time, by feature and by model.

From one measured run on `claude-sonnet-5-5` (2026-10-19):

| Step | Cost |
|---|---|
| One scout ranking (structured output) | $0.005 |
| One full curriculum track | $0.028 |
| One tutor turn (two model calls) | about $0.011 to $0.013 |
| One research angle with 2 web searches | $0.081 |

Topic research runs five angles, so it's the biggest single cost. Tutoring and grading are
cheap per turn. [Costs](COSTS.md) has the rest.

- **Set a limit:** add `AA_DAILY_BUDGET_USD=5` (any amount) to `.env` and restart. Once
  today's spend reaches it, new calls stop with a message saying what you spent. It's a soft
  limit: the call that crosses it can go over. For a hard limit, also set a spend limit on the
  key in the Anthropic Console.
- **Use your Claude subscription instead:** set `AA_LLM_BACKEND=agent_sdk` in `.env` (without
  Docker only). Calls then go through the Claude Agent SDK, which needs Claude Code installed
  and logged in. It's slower, but you don't pay per token. Usage shows the SDK's own cost
  estimate, and the daily limit doesn't apply.

## 8. Your data

Your whole record is one SQLite file on your machine.

- **Your data** (bottom of the sidebar): **Download backup (.db)** is a full copy you can
  restore. **Download full record (.json)** is every table as JSON, for reading or moving
  elsewhere.
- From a terminal, `just backup` and `just export` save the same files to `backups/`.
- To restore a backup, see [Back up and restore](BACKUP.md).
- **Remove the demo** when you're done: open its dashboard, click **Remove demo**, then
  **Yes, remove it**. This deletes the demo topic and everything in it, and nothing else.
