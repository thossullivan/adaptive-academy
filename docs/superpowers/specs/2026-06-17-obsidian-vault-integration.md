# Obsidian Vault Integration — local-first interop

**Date:** 2026-06-17
**Status:** approved (direction: both ingest + export; local-only, no cloud)
**Principle check:** Fully honors local-first / no-external-services / privacy. A vault is a
folder of markdown on disk; all I/O is local file I/O. No API, no keys, no data egress. Notion
and other cloud SaaS are **explicitly out of scope** (would be the first crack in local-first).

## Why

Don't silo the learner's materials. Their notes already live in Obsidian (plain `.md` +
`[[wikilinks]]` — the same idiom our memory system uses). Two flows:

- **Ingest** — point at a vault; selected notes become grounding `SourceDoc`s for
  research/curriculum/anchors. Curricula build on *your* material, not just arXiv.
- **Export** — concepts / track / progress get written back into the vault as linked notes
  *you own*, in a format that outlives the app.

## Design

### Config
- `Settings.obsidian_vault_path: str = ""` (env `AA_OBSIDIAN_VAULT_PATH`) as a default.
- API calls also accept an optional `vault_path` in the request body (overrides the default), so
  the frontend can set/change it without a restart (it persists the path in localStorage).

### Safety (even local I/O needs guards)
- `safe_vault_dir(path)`: resolve; must exist and be a directory; else error.
- `safe_child(vault, *parts)`: join + resolve; assert the result stays **inside** the resolved
  vault root (blocks `..` traversal / symlink escape). All writes go through it.
- Export writes **only** under a dedicated `Adaptive Academy/` subfolder we own — never touch the
  learner's own notes. Ingest **skips** that subfolder (no feedback loop).
- Ingest caps: max files scanned, max bytes read per file for the summary.

### Ingest (vault → SourceDoc)
- Recursively scan `*.md` under the vault (skipping `Adaptive Academy/` + dotfolders).
- Per note: title = frontmatter `title` ∥ first H1 ∥ filename; summary = frontmatter `summary`
  ∥ first paragraph (capped).
- Create `SourceDoc(topic_id, title, url="file://<abs path>", summary, tier=2, angle="vault",
  added_by="obsidian", status="proposed")`. Dedup by (topic_id, url).
- Returns count + titles. Notes then flow into curriculum/anchors via the existing consumption.

### Export (entities → vault notes)
- Folder: `<vault>/Adaptive Academy/<topic-slug>/`.
- `<topic-slug>.md` — hub note: frontmatter (`tags: [adaptive-academy]`), overview, the
  `track_to_markdown()` body, and a Concepts section linking each `[[concept]]`.
- `Concepts/<concept-slug>.md` — per concept: frontmatter (verdict, load_bearing), a summary of
  its latest assessments (verdict / score / gaps), backlink to the hub.
- Idempotent: regenerate on each export (we own the folder).
- **v1 limitation (noted, not hidden):** the per-concept verdict in export uses the latest
  grade + assessment summary, NOT the full 5-signal triangulation (that logic lives in
  frontend TS `competence.ts`). Porting `verdictRationale` to Python is a follow-up.

### API (`api/routes_vault.py`, prefix `/api/vault`)
- `POST /api/topics/{id}/vault/ingest` (body: optional `vault_path`, `subfolder`) → `{count, titles}`.
- `POST /api/topics/{id}/vault/export` (body: optional `vault_path`) → `{written: [paths]}`.
- `GET  /api/vault/status?vault_path=...` → `{configured, path, exists, is_dir, note_count}`.

### Frontend
- A **Vault** page (new "Connections" group in the Rail, or under Reflect): set/validate path
  (persisted in localStorage), show status, per-topic Ingest + Export buttons, last result.

## Build slices (each TDD'd, each routed to main)
1. **Pure core** `engine/vault.py`: slug, frontmatter render/parse, note scan (tmp dirs),
   `safe_vault_dir`/`safe_child`, entity→markdown renderers. + settings field.
2. **Orchestration + API**: `ingest_vault` / `export_vault` (DB ↔ files) + `routes_vault.py`.
3. **Frontend**: Vault page + Rail entry + api.ts methods.

## Out of scope (deferred)
- Notion / cloud connectors (explicit local-first exception — not now).
- Full triangulation in export (port `verdictRationale` to Python).
- Live file-watching / auto-sync (manual ingest/export buttons for v1).
- Round-trip editing of exported notes back into the DB (export is one-way for v1).
