# Releasing

A release is a version tag. Pushing one builds the container image (the API plus the built
frontend, from the [Dockerfile](../Dockerfile)) for `linux/amd64` and `linux/arm64` and publishes
it to GitHub Container Registry as `ghcr.io/thossullivan/adaptive-academy`
([`.github/workflows/release.yml`](../.github/workflows/release.yml)).

## Cut a release

1. Make sure `main` is green: `just test`, `cd frontend && npx vitest run && npm run check`,
   and `npm run test:e2e`.
2. Set the version in `pyproject.toml` (`version = "X.Y.Z"`) and commit it.
3. Tag and push:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

4. The workflow publishes `X.Y.Z`, `X.Y`, `latest`, and a `sha-…` tag. Check the run under the
   repo's **Actions** tab.

While the repository is private, the published package is private too. After making the repo
public, set the package's visibility to public under **Packages → adaptive-academy → Package
settings**.

## Run the published image

The same settings as `compose.yaml`, without building locally:

```bash
docker run -d --name adaptive-academy \
  -p 127.0.0.1:8000:8000 \
  -e ANTHROPIC_API_KEY="sk-ant-…" \
  -e AA_EMBEDDING_CACHE_DIR=/data/fastembed_cache \
  -v adaptive-academy-data:/data \
  ghcr.io/thossullivan/adaptive-academy:latest
```

Then open http://localhost:8000.

- **Obsidian vault (optional):** add `-v "/path/to/vault:/vault" -e AA_OBSIDIAN_VAULT_PATH=/vault`.
- **Linux file ownership:** add `-e AA_UID="$(id -u)" -e AA_GID="$(id -g)"` so vault exports
  are owned by you (the app runs as an unprivileged user; see the README's container notes).
- **Other settings** (models, daily spending limit) are the same `AA_*` variables as in
  [`.env.example`](../.env.example).
- **Upgrading:** `docker pull ghcr.io/thossullivan/adaptive-academy:latest`, then remove and
  re-run the container. The data volume is kept, and the container migrates the database on
  start. Take a backup first (`just backup`, or the **Your data** page).
