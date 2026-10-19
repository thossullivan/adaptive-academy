## What and why

<!-- What this changes, and the problem it solves. Link the issue or spec if there is one. -->

## How it was tested

<!-- The tests you added (and saw fail first), plus any manual checks. -->

## Checklist

- [ ] Tests written first and green: `just test`, `cd frontend && npx vitest run && npm run check`
- [ ] UI changes: `npm run test:e2e` passes, and the page has no horizontal scroll at 390px
- [ ] No live LLM calls in tests (new LLM code goes through the `llm/` registry)
- [ ] Schema change: an Alembic migration with plain `op.add_column` / `op.create_table`, plus a populated-db migration test
- [ ] No API keys, `.env` contents, real learning data, or databases in the diff
- [ ] Docs updated if behaviour changed (README, docs/FIRST_HOUR.md, `.env.example`)
