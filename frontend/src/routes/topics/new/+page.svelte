<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { billedTo } from '$lib/setup';
  import { setup } from '$lib/setup.svelte';
  import { topics } from '$lib/topics.svelte';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Field, Input, Textarea, SetupNotice } from '$lib/ui';

  let title = $state('');
  let goal = $state('');
  let prior_knowledge = $state('');
  let time_budget = $state('');
  let busy = $state(false);
  let status = $state('');

  const steps = ['Creating topic', 'Researching foundation', 'Ready to review'];
  let stepIdx = $state(-1);

  onMount(() => {
    setup.refresh();
  });

  async function start() {
    if (!title.trim() || !goal.trim() || busy || setup.blocked) return;
    busy = true;
    stepIdx = 0;
    status = 'Creating topic…';
    try {
      const topic = await api.createTopic({ title, goal, prior_knowledge, time_budget });
      await topics.refresh();
      topics.select(topic.id);
      stepIdx = 1;
      status = 'Researching foundational sources — this can take a moment…';
      await api.runResearch(topic.id);
      stepIdx = 2;
      await goto(`/topics/${topic.id}/review`);
    } catch (e) {
      status = 'Something went wrong: ' + (e as Error).message;
      busy = false;
      stepIdx = -1;
    }
  }
</script>

<Page eyebrow="New topic" title="What do you want to learn?" lead="A quick brief. The Researcher will assemble a foundation you can curate before any curriculum is built." width="narrow">
  <SetupNotice status={setup.status} class="mb-4" />

  <Card pad class="rise">
    <div class="flex flex-col gap-4">
      <Field label="Topic">
        <Input bind:value={title} placeholder="e.g. Build LLMs from scratch" disabled={busy} />
      </Field>
      <Field label="Your goal" hint="What does 'done' look like — the artifact you'll have shipped?">
        <Textarea bind:value={goal} placeholder="By the end I'll have…" disabled={busy} rows={3} />
      </Field>
      <Field label="Prior knowledge" hint="So the track starts at the right altitude.">
        <Textarea bind:value={prior_knowledge} placeholder="What you already know…" disabled={busy} rows={3} />
      </Field>
      <Field label="Time budget">
        <Input bind:value={time_budget} placeholder="e.g. ~10 hrs/week for 3 months" disabled={busy} />
      </Field>

      <div class="flex flex-col gap-2">
        <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button onclick={start} disabled={busy || setup.blocked || !title.trim() || !goal.trim()} size="lg">
            {busy ? 'Working…' : 'Research this topic →'}
          </Button>
          {#if setup.blocked}
            <span data-testid="submit-blocked" class="text-xs text-warn">Needs an Anthropic API key — see the setup note above.</span>
          {/if}
        </div>
        <p class="text-xs text-faint">
          Runs several model calls (multi-agent research) on {billedTo(setup.status)}. See the cost note in the README.
        </p>
      </div>
    </div>
  </Card>

  {#if busy || stepIdx >= 0}
    <div class="mt-4 flex flex-col gap-2 rise">
      {#each steps as s, i}
        <div class="flex items-center gap-3 text-sm">
          <span
            class="grid size-5 place-items-center rounded-full border text-[0.6rem]"
            style:border-color={i <= stepIdx ? 'var(--accent)' : 'var(--border)'}
            style:background={i < stepIdx ? 'var(--accent)' : 'transparent'}
            style:color={i < stepIdx ? 'var(--accent-fg)' : 'var(--muted)'}
          >
            {#if i < stepIdx}✓{:else if i === stepIdx}<span class="size-1.5 animate-pulse rounded-full bg-accent"></span>{:else}{i + 1}{/if}
          </span>
          <span class={i <= stepIdx ? 'text-fg-dim' : 'text-faint'}>{s}</span>
        </div>
      {/each}
      {#if status}<p class="mt-1 text-xs text-muted">{status}</p>{/if}
    </div>
  {/if}
</Page>
