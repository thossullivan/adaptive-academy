<script lang="ts">
  import { theme } from '$lib/theme.svelte';
  import { THEME_CHOICES, type ThemeChoice } from '$lib/theme';

  // Theme picker: System (follow the OS, the default) · Light · Dark, as a radio group with
  // roving focus (arrow keys move and select, per the ARIA radio-group pattern).
  const LABEL: Record<ThemeChoice, string> = { system: 'System', light: 'Light', dark: 'Dark' };

  let buttons: HTMLButtonElement[] = $state([]);

  function onKeydown(e: KeyboardEvent, i: number) {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const j = (i + step + THEME_CHOICES.length) % THEME_CHOICES.length;
    theme.set(THEME_CHOICES[j]);
    buttons[j]?.focus();
  }
</script>

<div
  role="radiogroup"
  aria-label="Theme"
  class="flex h-9 items-center gap-0.5 rounded-[var(--radius-sm)] border border-border bg-surface-2 p-0.5"
>
  {#each THEME_CHOICES as choice, i (choice)}
    {@const checked = theme.choice === choice}
    <button
      bind:this={buttons[i]}
      type="button"
      role="radio"
      aria-checked={checked}
      tabindex={checked ? 0 : -1}
      title={choice === 'system' ? `Follow your system (now ${theme.current})` : `${LABEL[choice]} theme`}
      onclick={() => theme.set(choice)}
      onkeydown={(e) => onKeydown(e, i)}
      class="flex h-full flex-1 items-center justify-center gap-1.5 rounded-[var(--radius-xs)] px-1.5 text-xs transition-colors {checked
        ? 'bg-surface text-fg ring-1 ring-border-strong'
        : 'text-muted hover:text-fg'}"
    >
      <svg viewBox="0 0 16 16" class="size-3.5 shrink-0" fill="none" aria-hidden="true">
        {#if choice === 'system'}
          <!-- monitor -->
          <rect x="1.75" y="2.5" width="12.5" height="8.5" rx="1.5" stroke="currentColor" stroke-width="1.3" />
          <path d="M5.5 14h5M8 11v3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
        {:else if choice === 'light'}
          <!-- sun -->
          <circle cx="8" cy="8" r="2.75" fill="currentColor" />
          <path
            d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M13 3l-1 1M4 12l-1 1"
            stroke="currentColor"
            stroke-width="1.3"
            stroke-linecap="round"
          />
        {:else}
          <!-- moon -->
          <path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7Z" fill="currentColor" opacity="0.85" />
        {/if}
      </svg>
      <span>{LABEL[choice]}</span>
    </button>
  {/each}
</div>
