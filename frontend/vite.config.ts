import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  // The Playwright e2e server sets its own cache dir, so its dependency pre-bundling never
  // re-optimizes (and reloads) a `just frontend` server running at the same time.
  cacheDir: process.env.AA_VITE_CACHE_DIR ?? 'node_modules/.vite',
  server: {
    // AA_API_URL lets the Playwright e2e run point at its own throwaway API.
    proxy: { '/api': process.env.AA_API_URL ?? 'http://localhost:8000' }
  }
});
