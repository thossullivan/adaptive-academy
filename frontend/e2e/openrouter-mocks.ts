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

export const agentSdkInContainer = {
  llm_backend: 'agent_sdk',
  provider: 'Claude subscription',
  llm_ready: false,
  message:
    "AA_LLM_BACKEND=agent_sdk needs Claude Code signed in on the host, and this container doesn't have it, so no " +
    'model calls can run. Unset AA_LLM_BACKEND to use ANTHROPIC_API_KEY, or set it to openrouter with ' +
    'OPENROUTER_API_KEY, then restart the container (`just up`). Or run the app on the host with `just api`.',
  models: { reasoning: 'claude-sonnet-5-5', copy: 'claude-haiku-5-5' },
  warnings: [] as string[]
};

export const mistypedBackend = {
  llm_backend: 'anthropic',
  provider: 'Anthropic',
  llm_ready: true,
  message: 'Anthropic API key configured.',
  models: { reasoning: 'claude-sonnet-5-5', copy: 'claude-haiku-5-5' },
  warnings: [] as string[],
  setup_warnings: [
    "AA_LLM_BACKEND is set to 'openroutr', which is not a backend this app knows, so it is using the " +
      'Anthropic API. Use anthropic, openrouter, or agent_sdk (or leave it unset), then restart the API.'
  ]
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
