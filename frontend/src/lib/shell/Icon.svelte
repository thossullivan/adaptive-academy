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
    notebook: 'M7 3h11a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H7V3Zm0 0v18M4 7h5M4 12h5M4 17h5M11 8h5M11 12h4',
    practice: 'M13 2L4 14h6l-1 8 9-12h-6l1-8Z',
    teach: 'M3 5h18v11H3zM8 20h8M12 16v4M9 10l2 2 4-4',
    wayfinder: 'M12 2l1.7 7.8L21 12l-7.3 1.7L12 22l-1.7-8.3L3 12l7.3-2.2z',
    data: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
    vault: 'M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7Zm8 4v4m-2-2h4',
    fleet: 'M12 3v9M12 5l6 3-6 2-6-2 6-3ZM6 12l6 2 6-2-1.5 4H7.5L6 12ZM4 18c1.3 1.3 2.7 1.3 4 0 1.3 1.3 2.7 1.3 4 0 1.3 1.3 2.7 1.3 4 0',
    usage: 'M4 20h16M7 16v-4M12 16V7M17 16v-6',
    // Voyage marks (Fleet, Wayfinder, comeback card, track deliverables): line glyphs in place
    // of colour emoji, so they take the theme's colour like every other icon.
    ship: 'M12 3v12M12 4.5 18 13h-6M11 7l-5 6h5M3.5 15.5h17l-2.3 3.5H5.8l-2.3-3.5Z',
    target: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4a5 5 0 1 0 0 10 5 5 0 0 0 0-10Zm0 4.2a.8.8 0 1 0 0 1.6.8.8 0 0 0 0-1.6Z',
    anchor: 'M12 7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm0 0V21M8.5 11h7M4.5 14a7.5 7.5 0 0 0 15 0M4.5 14l-1.5 1.5M19.5 14l1.5 1.5',
    flag: 'M5.5 21V3.5M5.5 4h12l-2.5 4.5 2.5 4.5h-12'
  };

  const filled = new Set(['dashboard', 'map', 'wayfinder']);
</script>

<svg viewBox="0 0 24 24" class={klass} fill={filled.has(name) ? 'currentColor' : 'none'} stroke={filled.has(name) ? 'none' : 'currentColor'} stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d={paths[name] ?? ''} />
</svg>
