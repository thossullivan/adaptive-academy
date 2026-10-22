# Contributing to Adaptive Academy

Thanks for your interest. Bug reports, ideas, docs, and code are all welcome.

## Ground rules

- **Be kind.** This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- **Keep it private.** Never commit API keys, real learning data, or a filled-in database.
  `.env` and `*.db` are gitignored. Keep it that way.
- **Keep changes small.** One thing per pull request.

## Getting set up

You need Python 3.12, [`uv`](https://docs.astral.sh/uv/), [`just`](https://github.com/casey/just),
and Node 22.12+ (or 20.19+). The [README](README.md) has the quick start, and
[docs/SETUP.md](docs/SETUP.md) has the details.

```bash
just setup                  # installs everything and creates .env if it's missing
just test                   # backend tests: these should pass before you start
cd frontend && npx vitest run && npm run check   # frontend tests and types
```

You only need `ANTHROPIC_API_KEY` in `.env` for real model calls. The tests never make any.
`just dev` runs the API and the frontend together (http://localhost:5173).

**Working on the UI without a key:** click **Explore a demo topic** on the empty home page (or
run `just seed`). It loads a realistic topic so every page has something on it. **Remove demo**
on its dashboard deletes it again.

### End-to-end tests

The Playwright tests drive the real UI at desktop and phone sizes. They start their own API on
a fresh, seeded database with no key, plus their own Vite server, on ports 18765 and 14173
(change them with `E2E_API_PORT` and `E2E_WEB_PORT`). They never touch your database, your
vault, or your dev servers.

```bash
cd frontend
npx playwright install chromium   # once
npm run test:e2e
npm run screenshots               # regenerate the README images in docs/images/
```

## How we work

1. **Branch** off `main` (`feat/…`, `fix/…`).
2. **Write the failing test first**, watch it fail, then make it pass. Backend tests use
   `pytest` (`just test`) and frontend tests use `vitest` (`npx vitest run`). The agents can be
   tested without real model calls through the scripted client. Keep new model-calling code
   behind the `llm/` registry so that stays true.
3. **Keep it clean.** `ruff check .` must pass. Run `pre-commit` if you have it. One statement
   per line, no `;`.
4. **Add a migration for every schema change.** Use `op.add_column`. Don't use
   `batch_alter_table` on tables that have data and foreign keys pointing at them. Include a
   migration test against a database with data in it. [`CLAUDE.md`](CLAUDE.md) has the rest of
   the conventions.
5. **New features** go in new `engine/` modules, with their own version-tagged prompts in
   `prompts.py`. Don't rework existing ones to fit.
6. **UI changes** need a Playwright test, and the page must not scroll sideways at 390px wide.
7. **Open a PR** that says why you made the change. The PR template has a checklist. Backend,
   frontend, and e2e tests must pass.

## Bigger features

Bigger features start as a short design in `docs/superpowers/specs/`, then a step-by-step plan
in `docs/superpowers/plans/`, then code. Those documents are a good way to see how the project
thinks. For a big idea, open an issue first so we can agree on the direction before you write
a full design.

## Finding something to work on

[`ROADMAP.md`](ROADMAP.md) lists what's planned. Issues labelled `good first issue` are small,
self-contained places to start.

## Reporting bugs and ideas

Open a [GitHub issue](../../issues). For a bug, say what you did, what you expected, and what
happened, with any logs. For a security problem, follow [SECURITY.md](SECURITY.md) instead.
Please don't open a public issue for it.
