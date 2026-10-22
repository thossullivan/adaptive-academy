import type { GradingStrictness, SetupStatus } from './types';

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

/** The level answers are graded at; standard when the API doesn't say. */
export function gradingStrictness(status: SetupStatus | null): GradingStrictness {
  return status?.grading_strictness ?? 'standard';
}

const STRICTNESS_NOTES: Record<Exclude<GradingStrictness, 'standard'>, string> = {
  lenient:
    'Grading is set to lenient (AA_GRADING_STRICTNESS). The grader gives credit for a key idea ' +
    'you show briefly or informally. The score limits for a missing idea or a misconception are ' +
    'the same at every level.',
  strict:
    'Grading is set to strict (AA_GRADING_STRICTNESS). The grader gives credit for a key idea ' +
    'only when you state it or show it clearly, and expects you to explain how it works, not ' +
    'just name it. The score limits for a missing idea or a misconception are the same at every level.'
};

/** A plain sentence about the grading level, or null at standard (nothing to say). */
export function strictnessNote(status: SetupStatus | null): string | null {
  const level = gradingStrictness(status);
  return level === 'standard' ? null : STRICTNESS_NOTES[level];
}

/** The setup card shows when LLM calls are blocked, when a configured model is experimental,
 *  when the configuration looks mistaken, or when grading isn't at the standard level. */
export function showSetupNotice(status: SetupStatus | null): boolean {
  return (
    llmBlocked(status) ||
    experimentalModels(status).length > 0 ||
    setupWarnings(status).length > 0 ||
    strictnessNote(status) !== null
  );
}
