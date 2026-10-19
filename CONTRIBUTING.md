# Contributing to Adaptive Academy

Thanks for your interest. Adaptive Academy is a local-first, generation-first learning
environment, built in public. Contributions — bug reports, ideas, docs, and code — are welcome.

## Ground rules

- **Be kind.** This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- **Local & private by design.** Never commit secrets, API keys, real learning data, or a
  populated database. `.env` and `*.db` are gitignored — keep it that way.
- **Small, focused changes.** One concern per pull request.

## Getting set up

Prerequisites: **Python 3.12**, [`uv`](https://docs.astral.sh/uv/), [`just`](https://github.com/casey/just),
and **Node 22.12+ (or 20.19+)** for the frontend. See [`README.md`](README.md) for the full quickstart.

```bash
just setup                  # checks prerequisites, installs everything, creates .env if missing
just test                   # backend suite: should be green before you start
cd frontend && npx vitest run && npm run check   # frontend tests + types
```

Add your `ANTHROPIC_API_KEY` to `.env` only when you need live model calls; the test suites never
make any. `just dev` runs the API and the frontend together (http://localhost:5173).

**Working on the UI without a key:** click **Explore a demo topic** on the empty home page (or run
`just seed`). It loads a realistic topic so every page has something to show, and **Remove demo**
on its dashboard deletes it again.

### End-to-end tests

The Playwright suite drives the real UI at desktop and phone sizes against a throwaway, seeded
API with no key:

```bash
cd frontend
npx playwright install chromium   # once
npm run test:e2e
npm run screenshots               # regenerate the README images in docs/images/
```

## Development workflow

The project is **spec-first and test-driven** — that discipline is the point, not overhead.

1. **Branch** off `main` (`feat/…`, `fix/…`).
2. **Write the failing test first**, watch it fail, then implement (TDD). Backend uses `pytest`
   (`just test`); frontend uses `vitest` (`npx vitest run`). The whole agent crew is testable
   with **no live API calls** via the scripted LLM client — please keep new LLM-backed code
   behind the `llm/` registry so it stays that way.
3. **Keep it clean.** `ruff check .` must pass (the repo is ruff-clean); run `pre-commit` if you
   have it installed. One statement per line — no `;`-chaining.
4. **Migrations for every schema change.** Use additive `op.add_column` (never
   `batch_alter_table` on populated, FK-referenced tables) and include a populated-DB
   migration test. See [`CLAUDE.md`](CLAUDE.md) for the conventions.
5. **New capabilities** go in as new `engine/` modules with their own version-tagged
   prompt(s) in `prompts.py`; don't destabilize existing ones.
6. **UI changes** need a Playwright test, and the page must not scroll sideways at 390px.
7. **Open a PR** with a clear description of the *why*. The PR template has the checklist;
   backend, frontend and e2e tests must be green.

## Larger features

Non-trivial features start as a short design spec in `docs/superpowers/specs/`, become a
bite-sized plan in `docs/superpowers/plans/`, then ship. Those documents *are* the build log —
they're a good place to see how the project thinks. For a big idea, open an issue to discuss
direction before investing in a full spec.

## Finding something to work on

[`ROADMAP.md`](ROADMAP.md) lists what's planned; items marked *good first issue* there are
self-contained starting points. Issues get the `good first issue` label as they're filed.

## Reporting bugs & ideas

Open a [GitHub issue](../../issues). For bugs, include what you did, what you expected, and what
happened (with any relevant logs). For security issues, see [SECURITY.md](SECURITY.md) instead —
please don't open a public issue.
