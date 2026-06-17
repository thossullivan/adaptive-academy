<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { topics } from '$lib/topics.svelte';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Field, Input, Textarea } from '$lib/ui';

  let title = $state('');
  let goal = $state('');
  let prior_knowledge = $state('');
  let time_budget = $state('');
  let busy = $state(false);
  let status = $state('');

  const steps = ['Creating topic', 'Researching foundation', 'Ready to review'];
  let stepIdx = $state(-1);

  async function start() {
    if (!title.trim() || !goal.trim() || busy) return;
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

      <Button onclick={start} disabled={busy || !title.trim() || !goal.trim()} size="lg" class="self-start">
        {busy ? 'Working…' : 'Research this topic →'}
      </Button>
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
