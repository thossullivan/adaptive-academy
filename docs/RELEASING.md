# Releasing

A release is a version tag. Pushing one builds the container image (the API plus the built
frontend, from the [Dockerfile](../Dockerfile)) for `linux/amd64` and `linux/arm64` and publishes
it to GitHub Container Registry as `ghcr.io/thossullivan/adaptive-academy`
([`.github/workflows/release.yml`](../.github/workflows/release.yml)).

## Cut a release

1. Make sure `main` is green: `just test`, `cd frontend && npx vitest run && npm run check`,
   and `npm run test:e2e`.
2. Bump the version in `pyproject.toml` (`version = "X.Y.Z"`) and in
   `src/adaptive_academy/__init__.py` (`__version__`), run `uv lock` to update the project entry
   in `uv.lock`, and commit all three.
3. Tag and push:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

4. The workflow runs the CI suites first, then publishes `X.Y.Z`, `X.Y`, `latest`, and a
   `sha-…` tag. Check the run under the repo's **Actions** tab. Only stable `vX.Y.Z` tags
   trigger it; build a pre-release with a manual run (**Run workflow**), which publishes only the
   `sha-…` tag.

While the repository is private, the published package is private too. After making the repo
public:

- set the package's visibility to public under **Packages → adaptive-academy → Package
  settings**;
- turn on **Settings → Code security → Private vulnerability reporting**, which the security
  policy and the issue forms' "Report a security problem" link rely on (it isn't available on a
  private repo).

## Run the published image

Equivalent to `compose.yaml`, without building locally:

```bash
export ANTHROPIC_API_KEY=sk-ant-…   # or set it in your shell profile; keeps it out of history below
docker run -d --name adaptive-academy --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -e ANTHROPIC_API_KEY \
  -e AA_EMBEDDING_CACHE_DIR=/data/fastembed_cache \
  -v adaptive-academy-data:/data \
  ghcr.io/thossullivan/adaptive-academy:latest
```

Then open http://localhost:8000.

- **Obsidian vault (optional):** add `-v "/path/to/vault:/vault" -e AA_OBSIDIAN_VAULT_PATH=/vault`.
- **Linux file ownership:** add `-e AA_UID="$(id -u)" -e AA_GID="$(id -g)"` so vault exports
  are owned by you (the app runs as an unprivileged user; see the README's container notes).
- **Other settings** (models, daily spending limit) are the same `AA_*` variables as in
  [`.env.example`](../.env.example), passed with `-e`. Don't pass `AA_DATABASE_URL` (and so don't
  use `--env-file .env` with the example file as is): the image already points it at `/data`,
  and the example's local path would make the container try to create the database inside the
  read-only app folder and exit.
- **Upgrading:**
  1. Back up first, from the running container: the **Your data** page, or
     `curl -OJ http://localhost:8000/api/export/backup`. (`just backup` backs up a host
     database, not the volume.)
  2. `docker pull ghcr.io/thossullivan/adaptive-academy:latest`, then remove and re-run the
     container. The data volume is kept, and the container migrates the database on start.
  3. Migrations only go forward: an older image can't start on a database a newer one has
     migrated. To roll back, restore the snapshot into the volume (README, "Back up and restore
     your data") before running the older image.
