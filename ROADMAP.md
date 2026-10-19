# Roadmap

What's planned, roughly in order. Nothing here is a promise; it's the current best guess, and
issues can change it. Each larger item starts as a design spec in `docs/superpowers/specs/`
before it is built (see [CONTRIBUTING.md](CONTRIBUTING.md)).

Items marked **good first issue** are self-contained and a good way into the codebase.

## Next

- **Browse past Tutor conversations.** Today every visit to the Tutor starts a new session, and
  past ones can't be opened. The design must keep the attempt gate per session: reopening an old
  conversation must not unlock `reveal_solution` without a new attempt.
- **Stop saving empty Tutor sessions.** Opening the Tutor page creates a conversation row even
  if nothing is sent. Create it on the first message instead. *Good first issue.*
- **New concepts start at the right difficulty.** The curriculum seeds every concept's estimate
  as "high", and the Tutor, roleplay, and paper probe read it to set assistance and challenge
  until the first graded assessment. Start ungraded concepts at a neutral level instead.
- **Reach roleplay and paper probe from a topic.** They are only reachable from a program
  milestone today, so a single topic (and the demo) can't use them.
- **Sidebar fits a laptop screen.** At 1440x900 the rail scrolls and hides the Reflect links.
  *Good first issue.*
- **Published container image.** The release workflow builds `ghcr.io/thossullivan/adaptive-academy`
  on a version tag (see [docs/RELEASING.md](docs/RELEASING.md)); the first tagged release makes
  `docker run` the quickest way in.

## Later

- **Reproduce, then extend (research apprenticeship, slice 2).** After a paper probe, reproduce
  a result and propose an extension. The paper probe's "what would you extend" answer is the
  on-ramp.
- **Sandboxed execution as a competence signal.** Run code artifacts against runnable acceptance
  checks (does it import, train, pass tests?) as one more input to the "shipped" signal. A
  security-sensitive build of its own.
- **Structured output on the Agent SDK path.** Subscription mode grades through the SDK's
  text path; port it to an in-process emit tool, as the SDK Tutor already does.
- **Memory follow-ups:** concept aliases in retrieval, per-source index status, and a re-fetch
  TTL for sources.
- **Voice for roleplay.** The seam is the text turn boundary (`run_roleplay_turn`).
- **Momentum recalibration.** "Steady" rarely shows because nearly every active learner reads
  "Cruising"; the constants live in `engine/momentum.py`.
- **Research mix.** Weight open courses, books, and canonical docs alongside papers when
  searching technical topics. *Good first issue (prompt change in `prompts.py`).*

## Not planned

- **Hosted or multi-user service.** The app is local-first: your learning record stays on your
  machine. (Each model call does send its content to Anthropic's API; see the README's cost and
  privacy note.)
- **Telemetry.** None, by design.
