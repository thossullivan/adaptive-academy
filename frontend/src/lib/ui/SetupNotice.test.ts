import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import SetupNotice from './SetupNotice.svelte';

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
  });

  it('renders nothing when ready or unknown', () => {
    for (const status of [
      { llm_backend: 'anthropic' as const, llm_ready: true, message: 'ok' },
      { llm_backend: 'agent_sdk' as const, llm_ready: true, message: 'ok' },
      null
    ]) {
      expect(render(SetupNotice, { props: { status } }).body).not.toContain('setup-notice');
    }
  });
});
