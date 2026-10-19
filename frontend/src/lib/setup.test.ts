import { describe, expect, it, vi } from 'vitest';
import { api } from './api';
import { billedTo, llmBlocked } from './setup';
import type { SetupStatus } from './types';

const ready: SetupStatus = { llm_backend: 'anthropic', llm_ready: true, message: 'ok' };
const missing: SetupStatus = { llm_backend: 'anthropic', llm_ready: false, message: 'No key' };
const sdk: SetupStatus = { llm_backend: 'agent_sdk', llm_ready: true, message: 'sdk' };

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
