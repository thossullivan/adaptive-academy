# Roadmap

What's planned, roughly in order. None of it is a promise, and issues can change the order or
the list. Each larger item starts as a design spec in `docs/superpowers/specs/`
before it is built (see [CONTRIBUTING.md](CONTRIBUTING.md)).

Items marked **good first issue** are self-contained and a good way into the codebase.

## Next

- **Browse past Tutor conversations.** Today every visit to the Tutor starts a new session, and
  past ones can't be opened. The design must keep the attempt gate per session: reopening an old
  conversation must not unlock `reveal_solution` without a new attempt.
- **New concepts start at the right difficulty.** The curriculum sets every new concept's
  estimate to "high". Until the first graded assessment, the Tutor, roleplay and paper probe use
  that estimate to decide how much to help and how hard to push. Ungraded concepts should start
  at a neutral level.
- **Reach roleplay and paper probe from a topic.** They are only reachable from a program
  milestone today, so a single topic (and the demo) can't use them.
- **Each learner's own time zone.** "Today" comes from the server's clock. Using the browser's
  time zone would give the right date on a shared or remote server.

## Later

- **Reproduce, then extend (research apprenticeship, slice 2).** After a paper probe, reproduce
  a result and propose an extension. The paper probe's "what would you extend" answer is the
  on-ramp.
- **Sandboxed execution as a competence signal.** Run the code you submit against real checks.
  Does it import? Does it train? Do its tests pass? The result becomes one more input to the
  "shipped" signal. Running untrusted code safely is a security project of its own.
- **Structured output on the Agent SDK path.** Subscription mode grades through the SDK's
  text path; port it to an in-process emit tool, as the SDK Tutor already does.
- **Memory follow-ups:** concept aliases in retrieval, per-source index status, and a re-fetch
  TTL for sources.
- **Voice for roleplay.** The seam is the text turn boundary (`run_roleplay_turn`).
- **Momentum recalibration.** "Steady" rarely shows because nearly every active learner reads
  "Cruising"; the constants live in `engine/momentum.py`.
- **Research mix.** Weight open courses, books, and canonical docs alongside papers when
  searching technical topics. *Good first issue (prompt change in `prompts.py`).*

## Principles that won't change

- **Local-first records.** Your learning record stays on your machine. Each model call still
  sends its content to the model's provider (see "Cost and privacy" in the README).
- **No telemetry.** None, by design.
