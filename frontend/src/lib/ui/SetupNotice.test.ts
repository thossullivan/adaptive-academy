import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import type { SetupStatus } from '$lib/types';
import SetupNotice from './SetupNotice.svelte';

const routerBase: SetupStatus = {
  llm_backend: 'openrouter',
  provider: 'OpenRouter',
  llm_ready: true,
  message: 'ok',
  models: { reasoning: 'anthropic/claude-sonnet-5.5', copy: 'anthropic/claude-haiku-5.5' },
  experimental_models: [],
  experimental_warning: null
};

const experimental: SetupStatus = {
  ...routerBase,
  models: { reasoning: 'deepseek/deepseek-v4', copy: 'anthropic/claude-haiku-5.5' },
  experimental_models: ['deepseek/deepseek-v4'],
  experimental_warning:
    'Experimental model: deepseek/deepseek-v4 (AA_MODEL_REASONING). It is not a Claude model.'
};

describe('SetupNotice', () => {
  it('explains the missing key and the exact fix', () => {
    const { body } = render(SetupNotice, {
      props: { status: { llm_backend: 'anthropic', llm_ready: false, message: 'No key' } }
    });
    expect(body).toContain('data-testid="setup-notice"');
    expect(body).toContain('ANTHROPIC_API_KEY');
    expect(body).toContain('cp .env.example .env');
    expect(body).toContain('just api');
    expect(body).toContain('just up');
    expect(body).toContain('AA_LLM_BACKEND=agent_sdk');
    expect(body).toContain('AA_LLM_BACKEND=openrouter');
  });

  it('renders nothing when ready or unknown', () => {
    for (const status of [
      { llm_backend: 'anthropic' as const, llm_ready: true, message: 'ok' },
      { llm_backend: 'agent_sdk' as const, llm_ready: true, message: 'ok' },
      routerBase,
      null
    ]) {
      const { body } = render(SetupNotice, { props: { status } });
      expect(body).not.toContain('setup-notice');
      expect(body).not.toContain('setup-experimental');
    }
  });

  it('names the OpenRouter key on the OpenRouter backend', () => {
    const { body } = render(SetupNotice, {
      props: { status: { ...routerBase, llm_ready: false, missing_key: 'OPENROUTER_API_KEY' } }
    });
    expect(body).toContain('data-testid="setup-notice"');
    expect(body).toContain('Add your OpenRouter API key');
    expect(body).toContain('OPENROUTER_API_KEY=sk-or-');
    expect(body).not.toContain('ANTHROPIC_API_KEY=sk-ant-');
    expect(body).toContain('passes through OpenRouter');
    expect(body).not.toContain('AA_LLM_BACKEND=agent_sdk');
  });

  it('marks an experimental model with a text label when the key is set', () => {
    const { body } = render(SetupNotice, { props: { status: experimental } });
    expect(body).toContain('data-testid="setup-experimental"');
    expect(body).not.toContain('data-testid="setup-notice"');
    expect(body).toContain('deepseek/deepseek-v4');
    expect(body).toContain('anthropic/claude-haiku-5.5');
    expect(body).toContain('It is not a Claude model.');
    // One "Experimental" label, on the flagged model only (plus the card's own badge).
    expect(body.match(/data-testid="experimental-label"/g)).toHaveLength(1);
  });

  it('lists experimental models inside the missing-key card too', () => {
    const { body } = render(SetupNotice, {
      props: { status: { ...experimental, llm_ready: false, missing_key: 'OPENROUTER_API_KEY' } }
    });
    expect(body).toContain('data-testid="setup-notice"');
    expect(body).toContain('data-testid="experimental-label"');
    expect(body).not.toContain('data-testid="setup-experimental"');
  });
});
