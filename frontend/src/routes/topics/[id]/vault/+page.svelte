<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { toasts } from '$lib/toast.svelte';
  import type { MemoryHit, MemoryStats, VaultStatus, VaultIngestResult, VaultExportResult, VaultExportAllResult, VaultSync } from '$lib/types';
  import { timeAgo } from '$lib/events';
  import { clearedSyncText, syncTargetText, updateSyncTarget } from '$lib/notebook';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Input, Badge, LiveStatus } from '$lib/ui';
  import MemorySearchResults from './MemorySearchResults.svelte';
  import { MAX_MEMORY_RESULTS, runMemoryReindex, runMemorySearch } from './memory-actions';

  const topicId = Number($page.params.id);
  const STORE_KEY = 'aa_vault_path';

  let path = $state('');
  let status = $state<VaultStatus | null>(null);
  // Concept notebooks sync to the checked vault (engine/notebook_sync.py).
  let sync = $state<VaultSync | null>(null);
  let syncError = $state('');
  let checking = $state(false);
  let exporting = $state(false);
  let exportingAll = $state(false);
  let ingesting = $state(false);
  let exportRes = $state<VaultExportResult | null>(null);
  let exportAllRes = $state<VaultExportAllResult | null>(null);
  let ingestRes = $state<VaultIngestResult | null>(null);
  let query = $state('');
  let resultLimit = $state('20');
  let searchHits = $state<MemoryHit[]>([]);
  let searching = $state(false);
  let searched = $state(false);
  let reindexing = $state(false);
  let stats = $state<MemoryStats | null>(null);
  let error = $state('');

  // Results that arrive asynchronously are announced through one polite live region.
  let announce = $state('');
  $effect(() => {
    if (status) announce = status.is_dir ? `Connected: ${status.note_count} markdown notes.` : 'Not a readable folder.';
  });
  $effect(() => {
    if (exportRes) announce = `Wrote ${exportRes.written.length} notes for this topic.`;
  });
  $effect(() => {
    if (exportAllRes) announce = `Mirrored ${exportAllRes.topics} topics into your vault.`;
  });
  $effect(() => {
    if (ingestRes) announce = `Added ${ingestRes.count} new sources.`;
  });
  $effect(() => {
    if (searched && !searching) announce = `${searchHits.length} result${searchHits.length === 1 ? '' : 's'}.`;
  });

  onMount(() => {
    path = localStorage.getItem(STORE_KEY) ?? '';
    if (path) check();
    else loadDefaultStatus();
    loadStats();
  });

  // No folder saved in this browser: show the AA_OBSIDIAN_VAULT_PATH vault, if one is set
  // (Docker sets /vault), so its sync state and problems are visible too.
  async function loadDefaultStatus() {
    const st = await api.vaultStatus('').catch(() => null);
    sync = st?.sync ?? null;
    status = st?.configured ? st : null;
  }

  async function check() {
    error = '';
    checking = true;
    try {
      localStorage.setItem(STORE_KEY, path.trim());
      status = await api.vaultStatus(path.trim());
      sync = status.sync ?? null;
      // A readable folder is also where concept notebooks sync from now on.
      await registerSync(status.is_dir);
    } catch (e) {
      error = String(e);
    } finally {
      checking = false;
    }
  }

  async function registerSync(isDir: boolean) {
    syncError = '';
    try {
      sync = (await updateSyncTarget(api.vaultSync, path, isDir)) ?? sync;
    } catch (e) {
      syncError = e instanceof Error ? e.message : String(e);
    }
  }

  // An emptied field stops notebooks syncing to the folder this browser set.
  async function onPathChange() {
    if (path.trim()) return;
    try {
      localStorage.removeItem(STORE_KEY);
    } catch {
      /* storage blocked */
    }
    await registerSync(false);
    await loadDefaultStatus();
    // With AA_OBSIDIAN_VAULT_PATH set, notes still sync there: say so, never "stopped".
    announce = clearedSyncText(sync);
  }

  const ready = $derived(!!status?.is_dir);

  async function loadStats() {
    stats = await api.memoryStats(topicId).catch(() => null);
  }

  async function search() {
    if (!query.trim() || searching) return;
    error = '';
    searching = true;
    searched = false;
    try {
      const result = await runMemorySearch(api.searchMemory, query, topicId, resultLimit);
      resultLimit = String(result.k);
      searchHits = result.hits;
      searched = true;
    } catch (e) {
      error = String(e);
    } finally {
      searching = false;
    }
  }

  async function reindex() {
    if (reindexing) return;
    error = '';
    reindexing = true;
    try {
      await runMemoryReindex(
        api.reindexMemory,
        {
          topic_id: topicId,
          vault_path: path.trim() || undefined
        },
        (message, tone) => toasts.show(message, tone)
      );
      await loadStats();
      if (query.trim()) await search();
    } catch (e) {
      error = String(e);
    } finally {
      reindexing = false;
    }
  }

  async function runExport() {
    error = '';
    exporting = true;
    exportRes = null;
    try {
      exportRes = await api.vaultExport(topicId, path.trim());
      await refreshSync();
    } catch (e) {
      error = String(e);
    } finally {
      exporting = false;
    }
  }

  async function runExportAll() {
    error = '';
    exportingAll = true;
    exportAllRes = null;
    try {
      exportAllRes = await api.vaultExportAll(path.trim());
      await refreshSync();
    } catch (e) {
      error = String(e);
    } finally {
      exportingAll = false;
    }
  }

  async function refreshSync() {
    sync = (await api.vaultStatus(path.trim()).catch(() => null))?.sync ?? sync;
  }

  async function runIngest() {
    error = '';
    ingesting = true;
    ingestRes = null;
    try {
      ingestRes = await api.vaultIngest(topicId, path.trim());
      await check(); // refresh note_count
    } catch (e) {
      error = String(e);
    } finally {
      ingesting = false;
    }
  }
</script>

<svelte:head><title>Vault · Adaptive Academy</title></svelte:head>

<Page
  eyebrow="Library"
  title="Obsidian vault"
  lead="Connect the app to the Obsidian notes you already keep. It only reads and writes files on this computer."
>
  <LiveStatus message={announce} />
  <div class="flex flex-col gap-5">
    <Card eyebrow="Vault folder" title="Where your notes live">
      <div class="flex flex-col gap-3">
        <div class="flex items-end gap-2">
          <div class="flex-1">
            <Input bind:value={path} onchange={onPathChange} aria-label="Vault folder path" placeholder="/Users/you/Obsidian/MyVault" />
          </div>
          <Button variant="outline" size="sm" onclick={check} disabled={checking || !path.trim()}>
            {checking ? 'Checking…' : 'Check'}
          </Button>
        </div>
        {#if status}
          {#if status.is_dir}
            <p class="text-sm text-fg-dim">
              <Badge tone="success" dot>connected</Badge>
              <span class="ml-2 nums">{status.note_count}</span> markdown notes ·
              <span class="text-faint">{status.path}</span>
            </p>
          {:else}
            <p class="text-sm" style:color="var(--danger)">
              Not a readable folder. Check the path is correct and exists on this machine.
            </p>
          {/if}
        {/if}
        {#if syncError}
          <p class="text-sm text-danger" role="status" data-testid="vault-sync-error">{syncError}</p>
        {/if}
        {#if sync && (sync.path || sync.last_error)}
          <div class="text-sm text-fg-dim" data-testid="vault-sync">
            {#if sync.path}
              <p class="[overflow-wrap:anywhere]">
                {syncTargetText(sync)}
                {#if sync.last_synced_at}<span class="text-faint">Last synced {timeAgo(sync.last_synced_at)}.</span>{/if}
              </p>
            {/if}
            {#if sync.last_error}
              <p class="mt-1 text-danger" role="status">
                {sync.last_error}{#if sync.problems > 1} ({sync.problems} notes need attention){/if}
              </p>
            {/if}
          </div>
        {/if}
        <p class="text-xs text-faint">
          The path is remembered in this browser only. You can also set a default with the
          <code>AA_OBSIDIAN_VAULT_PATH</code> environment variable.
        </p>
      </div>
    </Card>

    <div class="grid gap-5 md:grid-cols-2">
      <!-- Export -->
      <Card eyebrow="Export" title="Write learning → vault">
        <p class="mb-3 text-sm text-muted">
          Writes a topic hub note + per-concept notes (with verdicts and <code>[[links]]</code>)
          into a dedicated <code>Adaptive Academy/</code> folder. A concept note's notebook section is
          rewritten; anything you add outside it is kept. Re-run anytime to refresh.
        </p>
        <div class="flex flex-wrap items-center gap-2">
          <Button size="sm" onclick={runExport} disabled={!ready || exporting}>
            {exporting ? 'Writing…' : '↓ Export this topic'}
          </Button>
          <Button variant="outline" size="sm" onclick={runExportAll} disabled={!ready || exportingAll}>
            {exportingAll ? 'Writing all…' : 'Export all topics'}
          </Button>
        </div>
        {#if exportRes}
          <p class="mt-3 text-sm text-fg-dim">
            Wrote <span class="nums">{exportRes.written.length}</span> note{exportRes.written.length === 1 ? '' : 's'} for this topic.
          </p>
          {#if exportRes.problems?.length}
            <ul class="mt-2 list-disc pl-5 text-sm text-danger" data-testid="export-problems">
              {#each exportRes.problems as problem (problem)}
                <li>Left unchanged: {problem}</li>
              {/each}
            </ul>
          {/if}
        {/if}
        {#if exportAllRes}
          <p class="mt-3 text-sm text-fg-dim">
            Mirrored <span class="nums">{exportAllRes.topics}</span> topic{exportAllRes.topics === 1 ? '' : 's'}
            (<span class="nums">{exportAllRes.written.length}</span> notes) into your vault.
          </p>
        {/if}
      </Card>

      <!-- Ingest -->
      <Card eyebrow="Ingest" title="Vault notes → grounding sources">
        <p class="mb-3 text-sm text-muted">
          Registers your vault's markdown as <i>proposed</i> sources for this topic, so curricula
          and quizzes can be grounded in your own material. Safe to re-run — already-ingested notes
          are skipped.
        </p>
        <Button variant="outline" size="sm" onclick={runIngest} disabled={!ready || ingesting}>
          {ingesting ? 'Reading…' : '↑ Ingest notes'}
        </Button>
        {#if ingestRes}
          <p class="mt-3 text-sm text-fg-dim">
            Added <span class="nums">{ingestRes.count}</span> new source{ingestRes.count === 1 ? '' : 's'}.
            {#if ingestRes.titles.length}
              <span class="text-faint">Review them under Sources.</span>
            {/if}
          </p>
        {/if}
      </Card>
    </div>

    <Card eyebrow="Memory index" title="Search what Adaptive Academy remembers">
      <form
        class="flex flex-col gap-2 sm:flex-row"
        onsubmit={(e) => {
          e.preventDefault();
          search();
        }}
      >
        <Input
          bind:value={query}
          oninput={() => {
            searched = false;
            searchHits = [];
          }}
          aria-label="Search memory"
          placeholder="Search vault notes, sources, and prior learning…"
        />
        <label class="flex items-center gap-2 text-xs text-faint">
          Results
          <Input
            bind:value={resultLimit}
            type="number"
            min="1"
            max={MAX_MEMORY_RESULTS}
            class="w-20"
            aria-label="Maximum search results"
          />
        </label>
        <Button type="submit" variant="outline" size="sm" disabled={searching || !query.trim()}>
          {searching ? 'Searching…' : 'Search'}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onclick={reindex}
          disabled={reindexing || (!path.trim() && !status)}
        >
          {reindexing ? 'Reindexing…' : 'Reindex'}
        </Button>
      </form>

      {#if stats}
        <div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-faint">
          <Badge mono tone="neutral">{stats.retriever}</Badge>
          {#each Object.entries(stats.by_kind) as [kind, count] (kind)}
            <span>{kind.replaceAll('_', ' ')} <span class="nums text-fg-dim">{count}</span></span>
          {/each}
        </div>
      {/if}

      <MemorySearchResults hits={searchHits} {query} {searched} {searching} />
    </Card>

    {#if error}
      <p class="text-sm" style:color="var(--danger)" role="alert">{error}</p>
    {/if}
  </div>
</Page>
