import type { SetupStatus } from './types';

/** Block LLM-backed actions only when the API positively reports it can't run them.
 *  Unknown (still loading, or an older API without /api/setup) never blocks. */
export function llmBlocked(status: SetupStatus | null): boolean {
  return status?.llm_ready === false;
}

const isOpenRouter = (status: SetupStatus | null) => status?.llm_backend === 'openrouter';

/** Who pays for the model calls: the subscription in agent_sdk mode, else the API key. */
export function billedTo(status: SetupStatus | null): string {
  if (status?.llm_backend === 'agent_sdk') return 'your Claude subscription';
  return isOpenRouter(status) ? 'your OpenRouter key' : 'your Anthropic key';
}

/** The service the model calls go to, as the API names it. */
export function providerName(status: SetupStatus | null): string {
  return status?.provider ?? (isOpenRouter(status) ? 'OpenRouter' : 'Anthropic');
}

/** The environment variable the backend reads its key from. */
export function missingKey(status: SetupStatus | null): string {
  return status?.missing_key ?? (isOpenRouter(status) ? 'OPENROUTER_API_KEY' : 'ANTHROPIC_API_KEY');
}

/** The shape of a key for that variable, as shown in the setup steps. */
export function keyPlaceholder(envVar: string): string {
  return envVar === 'OPENROUTER_API_KEY' ? 'sk-or-…' : 'sk-ant-…';
}

/** Configured models the API marks experimental (not Claude). */
export function experimentalModels(status: SetupStatus | null): string[] {
  return status?.experimental_models ?? [];
}

export function isExperimental(model: string, status: SetupStatus | null): boolean {
  return experimentalModels(status).includes(model);
}

export function setupWarnings(status: SetupStatus | null): string[] {
  return status?.setup_warnings ?? [];
}

/** The setup card shows when LLM calls are blocked, when a configured model is experimental,
 *  or when the configuration looks mistaken. */
export function showSetupNotice(status: SetupStatus | null): boolean {
  return llmBlocked(status) || experimentalModels(status).length > 0 || setupWarnings(status).length > 0;
}
