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

  it('keeps the key steps in view and folds the other backends into a closed details', () => {
    const { body } = render(SetupNotice, {
      props: { status: { llm_backend: 'anthropic', llm_ready: false, message: 'No key' } }
    });
    const details = body.slice(body.indexOf('<details'), body.indexOf('</details>'));
    expect(details).toContain('data-testid="setup-alternatives"');
    expect(details).not.toMatch(/<details[^>]*\sopen/);
    expect(details).toContain('Use a Claude subscription or OpenRouter instead');
    expect(details).toContain('AA_LLM_BACKEND=agent_sdk');
    expect(details).toContain('OPENROUTER_API_KEY');
    // The fix itself stays outside the fold.
    const before = body.slice(0, body.indexOf('<details'));
    expect(before).toContain('Add your Anthropic API key');
    expect(before).toContain('cp .env.example .env');
    expect(body).not.toContain('—');
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

  it('explains a key in the wrong variable', () => {
    const { body } = render(SetupNotice, {
      props: {
        status: {
          ...routerBase,
          llm_ready: false,
          missing_key: 'OPENROUTER_API_KEY',
          key_hint: 'OPENROUTER_API_KEY holds an Anthropic key (it starts with sk-ant-).'
        }
      }
    });
    expect(body).toContain('data-testid="key-hint"');
    expect(body).toContain('holds an Anthropic key');
  });

  it('says agent_sdk cannot run in the container, without key steps', () => {
    const message = 'AA_LLM_BACKEND=agent_sdk needs Claude Code signed in on the host, and this container doesn’t have it.';
    const { body } = render(SetupNotice, {
      props: { status: { llm_backend: 'agent_sdk', provider: 'Claude subscription', llm_ready: false, message } }
    });
    expect(body).toContain('data-testid="setup-notice"');
    expect(body).toContain('The Claude subscription backend can');
    expect(body).toContain('this container');
    expect(body).not.toContain('cp .env.example .env');
  });

  it('shows setup warnings in their own card when calls can run', () => {
    const warning = "AA_LLM_BACKEND is set to 'openroutr', which is not a backend this app knows.";
    const { body } = render(SetupNotice, {
      props: { status: { llm_backend: 'anthropic', llm_ready: true, message: 'ok', setup_warnings: [warning] } }
    });
    expect(body).toContain('data-testid="setup-check"');
    expect(body).toContain('data-testid="setup-warning"');
    expect(body).toContain('Check your setup');
    expect(body).not.toContain('data-testid="setup-notice"');
  });

  it('names a grading level other than standard in its own card', () => {
    const { body } = render(SetupNotice, {
      props: { status: { llm_backend: 'anthropic', llm_ready: true, message: 'ok', grading_strictness: 'strict' } }
    });
    expect(body).toContain('data-testid="setup-grading"');
    expect(body).toContain('data-testid="grading-strictness"');
    expect(body).toContain('Grading setting');
    expect(body).toContain('AA_GRADING_STRICTNESS');
    expect(body).not.toContain('Check your setup');
    expect(body).not.toContain('data-testid="setup-notice"');
  });

  it('says nothing about grading at standard', () => {
    const { body } = render(SetupNotice, {
      props: { status: { llm_backend: 'anthropic', llm_ready: true, message: 'ok', grading_strictness: 'standard' } }
    });
    expect(body).not.toContain('grading-strictness');
    expect(body).not.toContain('setup-grading');
  });

  it('adds the grading level to the other cards', () => {
    const warning = "AA_LLM_BACKEND is set to 'openroutr', which is not a backend this app knows.";
    const check = render(SetupNotice, {
      props: {
        status: {
          llm_backend: 'anthropic',
          llm_ready: true,
          message: 'ok',
          setup_warnings: [warning],
          grading_strictness: 'lenient'
        }
      }
    }).body;
    expect(check).toContain('data-testid="setup-check"');
    expect(check).toContain('data-testid="grading-strictness"');
    const blocked = render(SetupNotice, {
      props: { status: { llm_backend: 'anthropic', llm_ready: false, message: 'No key', grading_strictness: 'lenient' } }
    }).body;
    expect(blocked).toContain('data-testid="setup-notice"');
    expect(blocked).toContain('data-testid="grading-strictness"');
  });

  it('gives the experimental label a screen-reader explanation', () => {
    const { body } = render(SetupNotice, { props: { status: experimental } });
    expect(body).toContain('class="sr-only"');
    expect(body).toContain('Not a Claude model');
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
