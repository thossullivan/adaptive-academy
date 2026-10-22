<script lang="ts">
  import { Button } from '$lib/ui';
  import { attemptShortcutLabel, composerAction } from './attempt';

  // The tutor's message box: Send asks or talks; Submit attempt sends the message as the
  // learner's attempt, which the app checks before the tutor replies (engine/attempt.py).
  let {
    value = $bindable(''),
    disabled = false,
    isMac = false,
    onsend,
    onattempt
  }: {
    value?: string;
    /** A send is in flight, or there is no concept to talk about. */
    disabled?: boolean;
    isMac?: boolean;
    onsend: () => void;
    onattempt: () => void;
  } = $props();

  const empty = $derived(!value.trim());

  function onkeydown(e: KeyboardEvent) {
    const action = composerAction(e);
    if (!action) return;
    e.preventDefault();
    if (action === 'attempt') onattempt();
    else onsend();
  }
</script>

<form
  class="mx-auto flex max-w-3xl flex-col gap-2 lg:flex-row lg:items-end"
  onsubmit={(e) => {
    e.preventDefault();
    onsend();
  }}
>
  <textarea
    bind:value
    rows="1"
    aria-label="Message the tutor"
    aria-describedby="tutor-composer-hint"
    placeholder="Ask the tutor… (it won't just hand you the answer)"
    {disabled}
    {onkeydown}
    class="max-h-40 min-h-[2.75rem] w-full flex-1 resize-none rounded-[var(--radius-md)] border border-control-border bg-surface-2 px-3.5 py-3 text-sm leading-relaxed text-fg placeholder:text-faint transition-colors hover:border-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-[var(--ring)] disabled:opacity-50"
  ></textarea>
  <div class="flex justify-end gap-2">
    <Button
      variant="outline"
      size="lg"
      class="px-4"
      disabled={disabled || empty}
      aria-keyshortcuts="Control+Enter Meta+Enter"
      aria-describedby="tutor-composer-hint"
      onclick={onattempt}>Submit attempt</Button
    >
    <Button type="submit" size="lg" class="px-5" disabled={disabled || empty} aria-keyshortcuts="Enter">Send</Button>
  </div>
</form>
<p id="tutor-composer-hint" class="mx-auto mt-1.5 hidden max-w-3xl text-xs text-muted sm:block">
  Enter sends. {attemptShortcutLabel(isMac)} submits it as your attempt: show your reasoning or a first step, and the
  tutor can then show the worked solution.
</p>
