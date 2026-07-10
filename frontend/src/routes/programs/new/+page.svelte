<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Field, Input, Textarea } from '$lib/ui';

  let title = $state('');
  let goal_statement = $state('');
  let focus_area = $state('');
  let target_depth = $state('');
  let prior_knowledge = $state('');
  let weekly_time_budget = $state('');
  let horizon = $state('');
  let busy = $state(false);
  let error = $state('');

  async function submit() {
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
  eyebrow="Voyages"
  title="New program"
  width="narrow"
  lead="Describe the substantial goal. Research drafts a milestone map you review before anything is built."
>
  <Card pad class="rise">
    <div class="flex flex-col gap-4">
      <Field label="Title">
        <Input bind:value={title} placeholder="PhD-level CS prep — custom LLMs" disabled={busy} />
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
      <div class="grid grid-cols-2 gap-4">
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
          <Input bind:value={prior_knowledge} placeholder="MS DS, physics UG, 10y eng" disabled={busy} />
        </Field>
      </div>
      {#if error}<p class="text-sm text-danger">{error}</p>{/if}
      <div>
        <Button onclick={submit} disabled={busy} size="lg" class="self-start">
          {busy ? 'Creating…' : 'Create program'}
        </Button>
      </div>
    </div>
  </Card>
</Page>
