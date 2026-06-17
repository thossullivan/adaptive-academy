<script lang="ts">
  let { name, class: klass = 'size-[18px]' }: { name: string; class?: string } = $props();

  // Stroke-based 24px icons, drawn to feel like instrument markings.
  const paths: Record<string, string> = {
    dashboard: 'M4 13h7V4H4v9Zm0 7h7v-5H4v5Zm9 0h7v-9h-7v9Zm0-16v5h7V4h-7Z',
    tutor: 'M4 5h16v11H8l-4 4V5Z',
    track: 'M4 6h2M4 12h2M4 18h2M9 6h11M9 12h11M9 18h7',
    assess: 'M9 4h6v2h3v15H6V6h3V4Zm-1 9 2 2 4-4',
    retention: 'M20 11a8 8 0 1 0-2 5m2-5v4m0-4h-4',
    sources: 'M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2V5Zm2 14h12M8 7h7M8 10h7',
    today: 'M12 7v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z',
    map: 'M12 3l1.6 3.6L17 8l-3.4 1.4L12 13l-1.6-3.6L7 8l3.4-1.4L12 3ZM5 15l.9 2L8 18l-2.1.9L5 21l-.9-2.1L2 18l2.1-1L5 15Zm13 1l.7 1.5L20 18l-1.3.6L18 20l-.7-1.4L16 18l1.3-.5L18 16Z',
    story: 'M5 4h9l5 5v11H5V4Zm9 0v5h5M8 13h8M8 16h5',
    practice: 'M13 2L4 14h6l-1 8 9-12h-6l1-8Z',
    teach: 'M3 5h18v11H3zM8 20h8M12 16v4M9 10l2 2 4-4',
    wayfinder: 'M12 2l1.7 7.8L21 12l-7.3 1.7L12 22l-1.7-8.3L3 12l7.3-2.2z'
  };

  const filled = new Set(['dashboard', 'map', 'wayfinder']);
</script>

<svg viewBox="0 0 24 24" class={klass} fill={filled.has(name) ? 'currentColor' : 'none'} stroke={filled.has(name) ? 'none' : 'currentColor'} stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d={paths[name] ?? ''} />
</svg>
