# Grading strictness setting and GRADE tune: design

Status: approved by Tom, 2026-10-23.

## Why

The grading eval (evals/grading) showed both default models never grade a weak answer as
mastered, but Claude Sonnet 5.5 capped 5 of 52 answers that cover an item (10%), against 2 for
DeepSeek. One example: a correct answer framed as minimising the negative log-likelihood was
capped for not saying "maximises the likelihood". Learners also differ: some want a strict
examiner, some a forgiving one.

## What changes

1. **GRADE tune.** The grade prompt says plainly that an equivalent formulation covers an item
   (minimising the negative of a quantity covers maximising it; a correct formula covers the
   statement it encodes; a standard abbreviation covers the term). Bump GRADE's version.
2. **A strictness setting.** `AA_GRADING_STRICTNESS` = `lenient`, `standard` (default), or
   `strict`.
   - It is rendered into the GRADE prompt as a template value (the same `str.format` mechanism
     every prompt already uses), selecting a short block of guidance per level. The caps the
     code enforces (0.70 missing, 0.50 misconception) do not change with strictness: strictness
     changes how the grader judges coverage and depth, not the rules.
   - `lenient`: credit an item when the answer shows the idea even if briefly or informally.
   - `standard`: today's behaviour after the tune.
   - `strict`: credit an item only when it is stated or clearly shown, and expect the mechanism
     to be explained, not just named.
   - The value is part of the recorded prompt tag (for example `assess.grade@v7:strict`), so
     grades made at different strictness can be told apart, and the eval report records it.
   - `/api/setup` reports it, the setup card names it when it isn't standard, and
     `.env.example` and docs/SETUP.md document it.
3. **Measured.** The eval runs on Sonnet 5.5 at each level after the change (about $0.25 each)
   and the README's grading section reports the default level's numbers.

## Tests

Prompt rendering for each level (and an unknown value falling back to standard with a setup
warning), prompt tag carries the level, caps unchanged across levels, the request snapshot for
the grade surface, the eval runner recording the level.
