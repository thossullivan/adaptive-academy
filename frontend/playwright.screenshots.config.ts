import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

// README screenshots (`npm run screenshots`), kept out of the normal e2e run: `npm run test:e2e`
// uses playwright.config.ts, which only matches e2e/*.e2e.ts.
//
// Same throwaway servers as the e2e run (e2e/start-api.sh: fresh SQLite db, no
// ANTHROPIC_API_KEY, no vault), but on their own ports and db file, seeded only with the usage
// rows in screenshots/seed_screenshots.py. The spec adds the demo topic via POST /api/demo and
// writes the images to docs/images/.
const API_PORT = Number(process.env.SHOTS_API_PORT ?? 18865);
const WEB_PORT = Number(process.env.SHOTS_WEB_PORT ?? 14273);

export default defineConfig({
  testDir: './screenshots',
  testMatch: '**/*.shots.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  timeout: 180_000,
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    browserName: 'chromium',
    colorScheme: 'dark',
    reducedMotion: 'reduce',
    locale: 'en-US',
    timezoneId: 'UTC'
  },
  webServer: [
    {
      command: './e2e/start-api.sh',
      env: {
        E2E_API_PORT: String(API_PORT),
        E2E_DB_NAME: 'screenshots.db',
        E2E_SEED_SCRIPT: fileURLToPath(new URL('./screenshots/seed_screenshots.py', import.meta.url)),
        // A daily limit, so the Usage page shows the budget bar as a configured user sees it.
        E2E_DAILY_BUDGET_USD: '5'
      },
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000
    },
    {
      command: `npx vite dev --port ${WEB_PORT} --strictPort`,
      env: { AA_API_URL: `http://127.0.0.1:${API_PORT}`, AA_VITE_CACHE_DIR: 'node_modules/.vite-shots' },
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000
    }
  ]
});
