<script lang="ts">
  import { page } from '$app/stores';
  import Page from '$lib/shell/Page.svelte';
  import { Button, Card } from '$lib/ui';

  // A bad URL or a failed page load: the app's own frame, a plain message, and a way back.
  const notFound = $derived($page.status === 404);
</script>

<svelte:head><title>{notFound ? 'Page not found' : 'Something went wrong'} · Adaptive Academy</title></svelte:head>

<Page
  eyebrow={notFound ? 'Page not found' : `Error ${$page.status}`}
  title={notFound ? "This page doesn't exist." : 'Something went wrong.'}
  width="narrow"
>
  <Card pad>
    <p class="text-sm text-fg-dim" data-testid="error-message">
      {#if notFound}
        The link may be old, or the address may have a typo. Your topics and notes are safe.
      {:else}
        This page couldn't load. Try again, or go back to the dashboard.
        {#if $page.error?.message}<span class="mt-2 block text-xs text-muted [overflow-wrap:anywhere]">{$page.error.message}</span>{/if}
      {/if}
    </p>
    <div class="mt-4">
      <Button href="/">Go to the dashboard</Button>
    </div>
  </Card>
</Page>
