<script lang="ts">
  import { tick } from 'svelte';
  import { page } from '$app/stores';
  import { topics } from '$lib/topics.svelte';
  import Rail from './Rail.svelte';
  import BrandMark from './BrandMark.svelte';

  // Below `md` the rail collapses into this top bar + off-canvas drawer. The drawer renders
  // the same Rail; at `md` and up this whole component is hidden and the static rail shows.
  const DRAWER_ID = 'mobile-nav-drawer';

  let open = $state(false);
  let menuButton: HTMLButtonElement | null = $state(null);
  let closeButton: HTMLButtonElement | null = $state(null);
  let drawer: HTMLDivElement | null = $state(null);

  async function show() {
    open = true;
    await tick();
    closeButton?.focus();
  }

  function hide({ restoreFocus = true } = {}) {
    if (!open) return;
    open = false;
    if (restoreFocus) menuButton?.focus();
  }

  // Close on navigation (a nav link, the brand link, or a topic switch).
  let lastPath = $page.url.pathname;
  $effect(() => {
    const path = $page.url.pathname;
    if (path !== lastPath) {
      lastPath = path;
      hide();
    }
  });

  // A topic switch on a non-topic page (/, /fleet, /programs) re-renders in place without
  // navigating, so watch the selected topic too. The first id arriving from the async topic
  // load (null → id) is not a switch.
  let lastTopic = topics.currentId;
  $effect(() => {
    const id = topics.currentId;
    if (id !== lastTopic) {
      const switched = lastTopic != null;
      lastTopic = id;
      if (switched) hide();
    }
  });

  // Lock body scroll while the drawer is open.
  $effect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  });

  // Growing past `md` (rotation, window resize) swaps in the static rail: drop the drawer.
  $effect(() => {
    const mq = window.matchMedia('(min-width: 48rem)');
    const onChange = () => {
      if (mq.matches) hide({ restoreFocus: false });
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  });

  function onDrawerClick(e: MouseEvent) {
    // Following any link closes the drawer, even one to the current page.
    if ((e.target as Element).closest('a[href]')) hide();
  }

  function onKeydown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      hide();
      return;
    }
    if (e.key !== 'Tab' || !drawer) return;
    // Keep Tab inside the modal drawer.
    const focusable = Array.from(
      drawer.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])')
    ).filter((el) => el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    // Focus on the drawer itself (a click on blank space) or outside it: pull it back in.
    if (!focusable.includes(document.activeElement as HTMLElement)) {
      e.preventDefault();
      (e.shiftKey ? last : first).focus();
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<header
  class="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-[color-mix(in_oklab,var(--surface)_70%,transparent)] px-4 backdrop-blur-xl md:hidden"
>
  <a href="/" class="flex min-w-0 items-center gap-2">
    <BrandMark class="size-7 shrink-0" />
    <span class="truncate font-display text-base leading-none text-fg">Adaptive <span class="text-accent">Academy</span></span>
  </a>
  <button
    bind:this={menuButton}
    type="button"
    aria-label="Open navigation"
    aria-expanded={open}
    aria-controls={DRAWER_ID}
    onclick={show}
    class="grid size-10 shrink-0 place-items-center rounded-[var(--radius-sm)] border border-border bg-surface-2 text-fg-dim transition-colors hover:border-border-strong hover:text-fg"
  >
    <svg viewBox="0 0 20 20" class="size-5" fill="none" aria-hidden="true">
      <path d="M3.5 6h13M3.5 10h13M3.5 14h13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
    </svg>
  </button>
</header>

<div class="md:hidden">
  <!-- Backdrop (pointer-only affordance; Escape and the close button cover keyboards) -->
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-40 bg-black/50 transition-opacity duration-200 motion-reduce:transition-none {open
      ? 'opacity-100'
      : 'pointer-events-none opacity-0'}"
    aria-hidden="true"
    onclick={() => hide()}
  ></div>

  <!-- Drawer: always mounted so it can slide; `invisible` + `inert` take it out of the
       tab order and accessibility tree while closed. Visibility flips instantly on open (so
       focus can land) but is transitioned on close (so the slide-out stays visible). The click handler only observes
       link clicks bubbling up from the rail. -->
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
  <div
    bind:this={drawer}
    id={DRAWER_ID}
    role="dialog"
    aria-modal="true"
    aria-label="Navigation"
    inert={!open}
    tabindex="-1"
    onclick={onDrawerClick}
    class="fixed inset-y-0 left-0 z-50 flex duration-250 ease-out motion-reduce:transition-none {open
      ? 'visible translate-x-0 transition-transform'
      : 'invisible -translate-x-full transition-[transform,visibility]'}"
  >
    <Rail class="static h-dvh w-72 max-w-[85vw] bg-surface shadow-[var(--shadow)]" />
    <button
      bind:this={closeButton}
      type="button"
      aria-label="Close navigation"
      onclick={() => hide()}
      class="absolute right-2 top-3.5 grid size-10 place-items-center rounded-[var(--radius-sm)] text-muted transition-colors hover:bg-surface-2 hover:text-fg"
    >
      <svg viewBox="0 0 20 20" class="size-4" fill="none" aria-hidden="true">
        <path d="M5 5l10 10M15 5L5 15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
      </svg>
    </button>
  </div>
</div>
