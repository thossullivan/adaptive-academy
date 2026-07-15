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
and Node 20+ for the frontend. See [`README.md`](README.md) for the full quickstart.

```bash
cp .env.example .env        # add your ANTHROPIC_API_KEY (BYOK)
uv sync                     # backend deps
just test                   # backend suite — should be green before you start
cd frontend && npm install && npx vitest run   # frontend deps + tests
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
6. **Open a PR** with a clear description of the *why*. Make sure backend and frontend tests
   are green.

## Larger features

Non-trivial features start as a short design spec in `docs/superpowers/specs/`, become a
bite-sized plan in `docs/superpowers/plans/`, then ship. Those documents *are* the build log —
they're a good place to see how the project thinks. For a big idea, open an issue to discuss
direction before investing in a full spec.

## Reporting bugs & ideas

Open a [GitHub issue](../../issues). For bugs, include what you did, what you expected, and what
happened (with any relevant logs). For security issues, see [SECURITY.md](SECURITY.md) instead —
please don't open a public issue.
