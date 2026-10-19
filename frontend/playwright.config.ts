import { defineConfig } from '@playwright/test';

// End-to-end tests run against a throwaway API (fresh SQLite db, deterministic seed, no
// ANTHROPIC_API_KEY) on :18765 and a Vite dev server on :14173 that proxies /api to it, so
// they never touch the developer's own db or the usual :8000 / :5173 dev servers.
const API_PORT = Number(process.env.E2E_API_PORT ?? 18765);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 14173);

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: 'retain-on-failure'
  },
  projects: [
    {
      name: 'desktop',
      use: { browserName: 'chromium', viewport: { width: 1440, height: 900 } }
    },
    {
      name: 'phone',
      use: {
        browserName: 'chromium',
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true
      }
    }
  ],
  webServer: [
    {
      command: './e2e/start-api.sh',
      env: { E2E_API_PORT: String(API_PORT) },
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000
    },
    {
      command: `npx vite dev --port ${WEB_PORT} --strictPort`,
      env: { AA_API_URL: `http://127.0.0.1:${API_PORT}`, AA_VITE_CACHE_DIR: 'node_modules/.vite-e2e' },
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000
    }
  ]
});
