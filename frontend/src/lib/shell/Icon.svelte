<script lang="ts">
  let { name, class: klass = 'size-[18px]' }: { name: string; class?: string } = $props();

  // Stroke-based 24px icons, drawn to feel like instrument markings.
  const paths: Record<string, string> = {
    dashboard: 'M4 13h7V4H4v9Zm0 7h7v-5H4v5Zm9 0h7v-9h-7v9Zm0-16v5h7V4h-7Z',
    tutor: 'M4 5h16v11H8l-4 4V5Z',
    track: 'M4 6h2M4 12h2M4 18h2M9 6h11M9 12h11M9 18h7',
    assess: 'M9 4h6v2h3v15H6V6h3V4Zm-1 9 2 2 4-4',
    retention: 'M20 11a8 8 0 1 0-2 5m2-5v4m0-4h-4',
    sources: 'M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2V5Zm2 14h12M8 7h7M8 10h7'
  };

  const filled = new Set(['dashboard']);
</script>

<svg viewBox="0 0 24 24" class={klass} fill={filled.has(name) ? 'currentColor' : 'none'} stroke={filled.has(name) ? 'none' : 'currentColor'} stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d={paths[name] ?? ''} />
</svg>
