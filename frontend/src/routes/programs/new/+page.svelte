<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { billedTo } from '$lib/setup';
  import { setup } from '$lib/setup.svelte';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Field, Input, Textarea, SetupNotice } from '$lib/ui';

  let title = $state('');
  let goal_statement = $state('');
  let focus_area = $state('');
  let target_depth = $state('');
  let prior_knowledge = $state('');
  let weekly_time_budget = $state('');
  let horizon = $state('');
  let busy = $state(false);
  let error = $state('');

  onMount(() => {
    setup.refresh();
  });

  async function submit() {
    if (busy || setup.blocked) return;
    if (!title.trim()) {
      error = 'Give the program a title.';
      return;
    }
    busy = true;
    error = '';
    try {
      const p = await api.createProgram({
        title,
        goal_statement,
        focus_area,
        target_depth,
        prior_knowledge,
        weekly_time_budget,
        horizon
      });
      await goto(`/programs/${p.id}`);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      busy = false;
    }
  }
</script>

<svelte:head><title>New program · Adaptive Academy</title></svelte:head>

<Page
  eyebrow="Programs"
  title="New program"
  width="narrow"
  lead="Describe your big goal. Research drafts a plan of milestones, and you check it before anything is built."
>
  <SetupNotice status={setup.status} class="mb-4" />

  <Card pad class="rise">
    <div class="flex flex-col gap-4">
      <Field label="Title">
        <Input bind:value={title} placeholder="PhD-level CS prep: custom LLMs" disabled={busy} />
      </Field>
      <Field label="Goal statement" hint="Why deep, why this.">
        <Textarea
          bind:value={goal_statement}
          placeholder="Research-ready: read frontier papers critically, reproduce results, extend one."
          disabled={busy}
          rows={3}
        />
      </Field>
      <Field label="Focus area">
        <Input bind:value={focus_area} placeholder="custom LLM models" disabled={busy} />
      </Field>
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Target depth">
          <Input bind:value={target_depth} placeholder="PhD-level" disabled={busy} />
        </Field>
        <Field label="Horizon">
          <Input bind:value={horizon} placeholder="2 years" disabled={busy} />
        </Field>
        <Field label="Weekly time budget">
          <Input bind:value={weekly_time_budget} placeholder="10h/week" disabled={busy} />
        </Field>
        <Field label="Prior knowledge">
          <Input bind:value={prior_knowledge} placeholder="undergrad maths, 3 years of Python" disabled={busy} />
        </Field>
      </div>
      {#if error}<p class="text-sm text-danger" role="alert">{error}</p>{/if}
      <div class="flex flex-col gap-2">
        <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button onclick={submit} disabled={busy || setup.blocked} size="lg">
            {busy ? 'Creating…' : 'Create program'}
          </Button>
          {#if setup.blocked}
            <span data-testid="submit-blocked" class="text-xs text-warn">Needs an API key. See the setup note above.</span>
          {/if}
        </div>
        <p class="text-xs text-faint">
          Drafting the plan next runs several model calls (research by several agents) on {billedTo(setup.status)}.
          See the cost note in the README.
        </p>
      </div>
    </div>
  </Card>
</Page>
