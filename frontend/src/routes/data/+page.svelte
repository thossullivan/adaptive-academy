<script lang="ts">
  import Page from '$lib/shell/Page.svelte';
  import { checkExport, startDownload } from '$lib/download';
  import { Button, Card } from '$lib/ui';

  // Check first, then let the browser download: a plain link alone would save an error
  // response (a JSON body) as if it were the file, and fetching the file to inspect it would
  // buffer a possibly large backup in the tab. The browser keeps the server's filename.
  const CHECK_URL = '/api/export/check';
  const BACKUP_URL = '/api/export/backup';
  const RECORD_URL = '/api/export/record';

  let busy = $state<string | null>(null);
  let error = $state('');

  async function download(url: string) {
    if (busy) return;
    busy = url;
    error = '';
    try {
      await checkExport(CHECK_URL);
      startDownload(url);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = null;
    }
  }
</script>

<Page
  eyebrow="Account"
  title="Your data"
  lead="Your learning record (topics, concepts, assessments, gates, conversations, and the agent trace) is one SQLite file on your machine. Take a copy any time."
  width="narrow"
>
  <div class="flex flex-col gap-5">
    <Card eyebrow="Where it lives" title="One local file">
      <ul class="flex flex-col gap-2 text-sm text-muted">
        <li>
          <span class="text-fg-dim">Running on your machine:</span>
          <code class="code">adaptive_academy.db</code> in the project folder (or wherever
          <code class="code">AA_DATABASE_URL</code> points).
        </li>
        <li>
          <span class="text-fg-dim">Running in Docker:</span>
          <code class="code">/data/adaptive_academy.db</code> inside the
          <code class="code">adaptive-academy-data</code> volume, which is why the downloads below exist.
        </li>
      </ul>
    </Card>

    <Card eyebrow="Download" title="Take it with you" accent>
      <div class="grid gap-4 sm:grid-cols-2">
        <div class="flex min-w-0 flex-col gap-2">
          <Button
            data-testid="download-backup"
            disabled={busy !== null}
            onclick={() => download(BACKUP_URL)}
          >
            {busy === BACKUP_URL ? 'Checking…' : 'Download backup (.db)'}
          </Button>
          <p class="text-xs leading-relaxed text-faint">
            A consistent snapshot of the whole database, safe to take while you work. This is the
            file you restore from.
          </p>
        </div>
        <div class="flex min-w-0 flex-col gap-2">
          <Button
            variant="outline"
            data-testid="download-record"
            disabled={busy !== null}
            onclick={() => download(RECORD_URL)}
          >
            {busy === RECORD_URL ? 'Checking…' : 'Download full record (.json)'}
          </Button>
          <p class="text-xs leading-relaxed text-faint">
            Every table as versioned JSON, for reading or moving elsewhere. Search indexes are left
            out; the app rebuilds them.
          </p>
        </div>
      </div>
      {#if error}
        <p class="mt-4 text-sm text-danger" role="alert" data-testid="download-error">
          Download failed: {error}
        </p>
      {/if}
      <p class="mt-4 text-xs text-faint">
        From a terminal: <code class="code">just backup</code> or <code class="code">just export</code>
        write the same files to <code class="code">backups/</code>.
      </p>
    </Card>

    <Card eyebrow="Restore" title="Put a snapshot back">
      <ol class="flex list-decimal flex-col gap-2 pl-5 text-sm text-muted marker:text-faint">
        <li>Download a backup of what you have now, then stop the app.</li>
        <li>
          On your machine:
          <pre class="pre">uv run aa restore backups/adaptive_academy-….db --force
uv run alembic upgrade head</pre>
          <span class="text-xs text-faint">
            <code class="code">aa restore</code> saves the current database to
            <code class="code">backups/</code> before replacing it.
          </span>
        </li>
        <li>
          In Docker: copy the snapshot into the volume as
          <code class="code">/data/adaptive_academy.db</code> (removing any stale
          <code class="code">-wal</code>/<code class="code">-shm</code> files), then
          <code class="code">just up</code>; the container migrates on start.
        </li>
      </ol>
      <p class="mt-4 text-xs text-faint">
        Full steps are in the README under "Back up and restore your data".
      </p>
    </Card>
  </div>
</Page>

<style>
  .code {
    font-family: var(--font-mono);
    font-size: 0.85em;
    color: var(--fg-dim);
    background: var(--surface-3);
    padding: 0.05em 0.35em;
    border-radius: var(--radius-xs);
    overflow-wrap: anywhere;
  }
  .pre {
    margin-top: 0.5rem;
    margin-bottom: 0.25rem;
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: 0.75rem;
    line-height: 1.6;
    color: var(--fg-dim);
    background: var(--surface-3);
    padding: 0.6rem 0.75rem;
    border-radius: var(--radius-sm);
  }
</style>
