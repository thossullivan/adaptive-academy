# Setup details

The [README](../README.md#get-started) has the short version. This page covers the rest.

## Docker

`just up` builds one container with the API and the frontend, at http://localhost:8000. The
database lives in a Docker volume called `adaptive-academy-data`.

```bash
just up                    # build and start
just logs                  # follow the logs
just down                  # stop
just db-migrate-to-volume  # optional: copy an existing local database into the volume
```

No `just`? Run `mkdir -p data/vault && docker compose up -d --build`. Use
`docker compose logs -f` and `docker compose down` for the other two.

Things to know:

- The container only supports an API key (`ANTHROPIC_API_KEY`). The Claude subscription
  option (`AA_LLM_BACKEND=agent_sdk`) only works without Docker.
- Don't point a local install and the container at the same database file. After
  `just db-migrate-to-volume`, the repo's `adaptive_academy.db` is left alone.
- The app runs as an ordinary user (uid/gid 1000 by default), not as root. You can change
  this with `AA_UID` and `AA_GID` in `.env`. On start, the container gives `/data` to that
  user. Volumes from older versions were owned by root, and the first start fixes them. It
  never changes ownership of anything in your vault.
- **Linux:** put your own uid and gid in `.env`, so the notes the app writes to your vault
  belong to you. `.env` doesn't run commands, so add the numbers like this:
  `echo "AA_UID=$(id -u)" >> .env && echo "AA_GID=$(id -g)" >> .env`.
  On macOS, Docker Desktop and OrbStack already give these files your own user, so the
  default is fine. If the vault isn't writable, the app still starts, and a vault export
  tells you what to set.

### Obsidian vault

The vault is mounted read-write at `/vault` inside the container. Set `OBSIDIAN_VAULT_PATH`
in `.env` to your vault folder. If you leave it unset, the app uses `./data/vault` in the
repo (gitignored), and exports land there.

- `just up` creates `./data/vault` for you. If you run `docker compose up` yourself on
  Linux, run `mkdir -p data/vault` first, or Docker creates it owned by root.
- If the path has spaces, put it in quotes, for example
  `OBSIDIAN_VAULT_PATH="/Users/you/Library/Mobile Documents/..."`. Without quotes, `just`
  can't read the file.

## Without Docker

`just setup` is safe to run again and never overwrites your `.env`. It does the same as:

```bash
cp .env.example .env          # only if .env doesn't exist yet
just install                  # Python packages (uv sync)
uv run alembic upgrade head   # create the database
cd frontend && npm ci && cd ..
```

`just dev` starts the API on port 8000 and the frontend on port 5173. Their output is marked
`[api]` and `[web]`, and if one stops, so does the other. To use other ports, set
`AA_API_PORT` and `AA_WEB_PORT`, for example `AA_API_PORT=8001 just dev` while the container
is using 8000. If you'd rather use two terminals, run `just api` and `just frontend`.

Some things that can trip you up:

- **Start the API with `just dev` or `just api`.** Both read `.env`. Running
  `uv run uvicorn ...` yourself skips it, so the key is missing and AI features return
  errors.
- **An old frontend build.** `cd frontend && npm run build` leaves a `frontend/build/`
  folder, and `just api` then serves that copy at http://localhost:8000 even after it goes
  stale. Delete it with `rm -rf frontend/build`. The dev frontend on port 5173 isn't
  affected.

### The demo topic

`just seed` adds the same demo topic as the **Explore a demo topic** button on the empty home
page. It needs no API key. Remove it from its dashboard when you're done.

## Models

The defaults are `claude-sonnet-5-5` for reasoning and `claude-haiku-5-5` for shorter text,
in Docker too. If one isn't available to your key, set `AA_MODEL_REASONING` or
`AA_MODEL_COPY` in `.env` and restart the API. Leave them blank to use the defaults of the
backend you're on.

## OpenRouter

To run on an OpenRouter key instead of an Anthropic one, add these to `.env` and restart:

```bash
AA_LLM_BACKEND=openrouter
OPENROUTER_API_KEY=sk-or-...
```

This works in Docker too. The defaults are `anthropic/claude-sonnet-5.5` and
`anthropic/claude-haiku-5.5`. Model names on OpenRouter are `vendor/model`, for example
`deepseek/deepseek-v4.1-flash-1017`.

Things to know:

- Claude models get full support. Any other model works but is marked **Experimental** on
  the setup card and the Usage page. In a full run, DeepSeek V4.1 Flash cost about a quarter
  of Claude, but tutor turns took 7 to 28 seconds instead of a few.
- Each request asks OpenRouter to skip providers that may train on your prompts. It doesn't
  turn off storage: providers can still keep prompts for things like abuse checks.
- The app never sends your Anthropic key to OpenRouter, even if `ANTHROPIC_BASE_URL` points
  there, and it warns you if a key is in the wrong variable.
- What OpenRouter charges is recorded on the Usage page and counts toward your daily limit.

## Claude subscription (without Docker only)

`AA_LLM_BACKEND=agent_sdk` sends calls through the Claude Agent SDK, using your Claude plan
instead of an API key. It needs Claude Code installed and logged in on the same machine, so it
doesn't work in Docker: there the setup card says so and AI features stay off until you
change it.

## Time zone

"Today" (for the date in prompts and the daily limit) is the server's local day. In Docker
that's UTC unless you set `TZ` in `.env`, for example `TZ=America/Los_Angeles`.

## Better search (optional)

By default, search over your notes and sources uses SQLite full-text search. The `memory`
extra adds vector search on top:

```bash
just setup --memory   # or: uv sync --extra memory
```

It downloads a small embedding model (about 130 MB) once, into `AA_EMBEDDING_CACHE_DIR`. The
container keeps it on the data volume. On a machine with no internet, set
`AA_EMBEDDING_ALLOW_DOWNLOAD=false` to only use a model that's already downloaded. Running
plain `just setup` or `uv sync` later removes the extra again, so add `--memory` each time.

All the other settings are listed, with comments, in [`.env.example`](../.env.example).
