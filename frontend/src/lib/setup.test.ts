import { describe, expect, it, vi } from 'vitest';
import { api } from './api';
import {
  billedTo,
  experimentalModels,
  isExperimental,
  keyPlaceholder,
  llmBlocked,
  missingKey,
  providerName,
  setupWarnings,
  showSetupNotice
} from './setup';
import type { SetupStatus } from './types';

const ready: SetupStatus = { llm_backend: 'anthropic', llm_ready: true, message: 'ok' };
const missing: SetupStatus = { llm_backend: 'anthropic', llm_ready: false, message: 'No key' };
const sdk: SetupStatus = { llm_backend: 'agent_sdk', llm_ready: true, message: 'sdk' };
const router: SetupStatus = {
  llm_backend: 'openrouter',
  provider: 'OpenRouter',
  llm_ready: true,
  message: 'ok',
  models: { reasoning: 'anthropic/claude-sonnet-5.5', copy: 'anthropic/claude-haiku-5.5' },
  experimental_models: []
};
const routerMissing: SetupStatus = { ...router, llm_ready: false, missing_key: 'OPENROUTER_API_KEY' };
const routerExperimental: SetupStatus = {
  ...router,
  models: { reasoning: 'deepseek/deepseek-v4', copy: 'anthropic/claude-haiku-5.5' },
  experimental_models: ['deepseek/deepseek-v4'],
  experimental_warning: 'Experimental model: deepseek/deepseek-v4 (AA_MODEL_REASONING).'
};

describe('backend wording', () => {
  it('names the provider and the key the backend needs', () => {
    expect(providerName(router)).toBe('OpenRouter');
    expect(providerName(missing)).toBe('Anthropic');
    expect(providerName({ ...router, provider: undefined })).toBe('OpenRouter');
    expect(providerName(null)).toBe('Anthropic');
    expect(missingKey(routerMissing)).toBe('OPENROUTER_API_KEY');
    expect(missingKey({ ...routerMissing, missing_key: undefined })).toBe('OPENROUTER_API_KEY');
    expect(missingKey(missing)).toBe('ANTHROPIC_API_KEY');
    expect(keyPlaceholder('OPENROUTER_API_KEY')).toBe('sk-or-…');
    expect(keyPlaceholder('ANTHROPIC_API_KEY')).toBe('sk-ant-…');
  });

  it('bills OpenRouter calls to the OpenRouter key', () => {
    expect(billedTo(router)).toBe('your OpenRouter key');
  });
});

describe('experimental models', () => {
  it('reads the flagged models and labels only those', () => {
    expect(experimentalModels(routerExperimental)).toEqual(['deepseek/deepseek-v4']);
    expect(experimentalModels(ready)).toEqual([]);
    expect(experimentalModels(null)).toEqual([]);
    expect(isExperimental('deepseek/deepseek-v4', routerExperimental)).toBe(true);
    expect(isExperimental('anthropic/claude-haiku-5.5', routerExperimental)).toBe(false);
  });

  it('shows the setup card when blocked, experimental, or misconfigured', () => {
    expect(showSetupNotice(routerMissing)).toBe(true);
    expect(showSetupNotice(routerExperimental)).toBe(true);
    const mistyped = { ...ready, setup_warnings: ["AA_LLM_BACKEND is set to 'openroutr'"] };
    expect(setupWarnings(mistyped)).toHaveLength(1);
    expect(showSetupNotice(mistyped)).toBe(true);
    expect(setupWarnings(ready)).toEqual([]);
    expect(showSetupNotice(router)).toBe(false);
    expect(showSetupNotice(ready)).toBe(false);
    expect(showSetupNotice(null)).toBe(false);
  });
});

describe('llmBlocked', () => {
  it('blocks only when the API says LLM calls cannot run', () => {
    expect(llmBlocked(missing)).toBe(true);
    expect(llmBlocked(ready)).toBe(false);
    expect(llmBlocked(sdk)).toBe(false);
  });

  it('never blocks on an unknown status', () => {
    expect(llmBlocked(null)).toBe(false);
  });
});

describe('billedTo', () => {
  it('names the subscription in agent_sdk mode and the key otherwise', () => {
    expect(billedTo(sdk)).toBe('your Claude subscription');
    expect(billedTo(ready)).toBe('your Anthropic key');
    expect(billedTo(null)).toBe('your Anthropic key');
  });
});

describe('api.getSetup', () => {
  it('reads /api/setup', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => missing }) as any;
    const out = await api.getSetup();
    expect((globalThis.fetch as any).mock.calls[0][0]).toBe('/api/setup');
    expect(out.llm_ready).toBe(false);
  });
});
