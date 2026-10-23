<script lang="ts">
  import { tick, type Snippet } from 'svelte';
  import Button from './Button.svelte';

  // A destructive action with an inline confirm step (removing the demo, deleting a topic).
  // The step swaps buttons under a keyboard user's focus, so focus moves to the safe choice
  // (Cancel) when it appears and back to the action button when it goes away. Escape cancels.
  // The question names the group; the optional detail describes it.
  let {
    label,
    question,
    detail = undefined,
    confirmLabel,
    busyLabel,
    busy = false,
    onconfirm,
    variant = 'outline',
    testid = undefined
  }: {
    label: string;
    question: string;
    detail?: Snippet;
    confirmLabel: string;
    busyLabel: string;
    busy?: boolean;
    onconfirm: () => void | Promise<void>;
    variant?: 'outline' | 'ghost' | 'danger';
    testid?: string;
  } = $props();

  const uid = $props.id();
  let open = $state(false);
  let root: HTMLDivElement | null = $state(null);

  async function ask() {
    open = true;
    await tick();
    root?.querySelector<HTMLElement>('[data-confirm-cancel]')?.focus();
  }

  async function cancel() {
    open = false;
    await tick();
    root?.querySelector<HTMLElement>('[data-confirm-trigger]')?.focus();
  }
</script>

<div class="contents" bind:this={root} data-testid={testid}>
  {#if open}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div
      class="flex flex-wrap items-center gap-2"
      role="group"
      aria-labelledby="{uid}-question"
      aria-describedby={detail ? `${uid}-detail` : undefined}
      onkeydown={(e) => {
        if (e.key === 'Escape' && !busy) {
          e.preventDefault();
          cancel();
        }
      }}
    >
      <span id="{uid}-question" class="text-sm text-fg [overflow-wrap:anywhere]">{question}</span>
      {#if detail}
        <p id="{uid}-detail" class="basis-full text-xs leading-relaxed text-muted">{@render detail()}</p>
      {/if}
      <div class="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="danger" onclick={onconfirm} disabled={busy}>
          {busy ? busyLabel : confirmLabel}
        </Button>
        <Button size="sm" variant="ghost" onclick={cancel} disabled={busy} data-confirm-cancel>Cancel</Button>
      </div>
    </div>
  {:else}
    <Button size="sm" {variant} onclick={ask} data-confirm-trigger>{label}</Button>
  {/if}
</div>
