import type { Page } from '@playwright/test';

// Mocked API states for the OpenRouter backend (AA_LLM_BACKEND=openrouter). The e2e API runs
// keyless on the default backend, so these states exist only as mocked responses; shared by
// openrouter.e2e.ts and the axe audit (a11y.e2e.ts).

export const SLUGS = { reasoning: 'anthropic/claude-sonnet-5.5', copy: 'anthropic/claude-haiku-5.5' };
export const EXPERIMENTAL = 'deepseek/deepseek-v4';
const WARNING =
  `Experimental model: ${EXPERIMENTAL} (AA_MODEL_REASONING). It is not a Claude model, so structured ` +
  "answers, web search, and the tutor's tools may not work as well. Claude models through OpenRouter " +
  'are fully supported.';

export const openrouterMissingKey = {
  llm_backend: 'openrouter',
  provider: 'OpenRouter',
  llm_ready: false,
  message: 'No OPENROUTER_API_KEY configured.',
  missing_key: 'OPENROUTER_API_KEY',
  models: SLUGS,
  experimental_models: [] as string[],
  experimental_warning: null as string | null,
  warnings: [] as string[]
};

export const openrouterExperimental = {
  ...openrouterMissingKey,
  llm_ready: true,
  message: 'OpenRouter API key configured.',
  missing_key: null,
  models: { ...SLUGS, reasoning: EXPERIMENTAL },
  experimental_models: [EXPERIMENTAL],
  experimental_warning: WARNING
};

export async function mockSetup(page: Page, json: object) {
  await page.route('**/api/setup', (route) => route.fulfill({ json }));
}

/** The real usage report from the seeded API, as the OpenRouter backend would show it, plus
 *  one call on an experimental model. */
export async function mockOpenRouterUsage(page: Page) {
  await page.route('**/api/usage', async (route) => {
    const response = await route.fetch();
    const report = await response.json();
    const template = { ...report.by_model[0] };
    report.backend = 'openrouter';
    report.by_model = [
      ...report.by_model.map((m: object) => ({ ...m, experimental: false })),
      {
        ...template,
        model: EXPERIMENTAL,
        calls: 2,
        cost_usd: 0.004,
        api_cost_usd: 0.004,
        unpriced_calls: 0,
        experimental: true
      }
    ];
    await route.fulfill({ response, json: report });
  });
}
