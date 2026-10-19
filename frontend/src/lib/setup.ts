import type { SetupStatus } from './types';

/** Block LLM-backed actions only when the API positively reports it can't run them.
 *  Unknown (still loading, or an older API without /api/setup) never blocks. */
export function llmBlocked(status: SetupStatus | null): boolean {
  return status?.llm_ready === false;
}

/** Who pays for the model calls — the subscription in agent_sdk mode, else the API key. */
export function billedTo(status: SetupStatus | null): string {
  return status?.llm_backend === 'agent_sdk' ? 'your Claude subscription' : 'your Anthropic key';
}
