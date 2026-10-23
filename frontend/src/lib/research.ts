// Running topic research from the UI. Shared by the new-topic page and the Sources page's
// "Research again", so both say the same thing while it runs and when it fails.
import { api, ApiError } from './api';

export const RESEARCH_PROGRESS = 'Finding sources. This can take a moment…';

/** Said when research for the topic is already running (in another tab, or still going from
 *  the new-topic page): the Sources page waits for it and reloads. */
export const RESEARCH_RUNNING = 'Research is still running for this topic. This page updates when it finishes.';

/** How often the Sources page asks whether research has finished. */
export const RESEARCH_POLL_MS = 3000;

/** The line shown when research (or creating its topic) fails. The API's own detail says
 *  how to fix it, e.g. "Anthropic did not accept the API key…". */
export function researchFailed(e: unknown): string {
  return 'Something went wrong: ' + (e instanceof Error ? e.message : String(e));
}

/** Whether the API refused to research because research for the topic is already running
 *  (409). The other 409, research that already ran, keeps the API's own words. */
export function researchAlreadyRunning(e: unknown): boolean {
  return e instanceof ApiError && e.status === 409 && !/already has a foundation/i.test(e.message);
}

export type ResearchOutcome = 'done' | 'running' | 'failed';

/** Run research for `topicId`, reporting progress and any failure through `status`.
 *  'running': research for the topic was already running, and `status` says so. */
export async function researchTopic(
  topicId: number,
  status: (text: string) => void,
  run: (topicId: number) => Promise<unknown> = api.runResearch
): Promise<ResearchOutcome> {
  status(RESEARCH_PROGRESS);
  try {
    await run(topicId);
    return 'done';
  } catch (e) {
    if (researchAlreadyRunning(e)) {
      status(RESEARCH_RUNNING);
      return 'running';
    }
    status(researchFailed(e));
    return 'failed';
  }
}

/** Run research for `topicId`, reporting progress and any failure through `status`.
 *  Resolves true when research finished. */
export async function runTopicResearch(
  topicId: number,
  status: (text: string) => void,
  run: (topicId: number) => Promise<unknown> = api.runResearch
): Promise<boolean> {
  return (await researchTopic(topicId, status, run)) === 'done';
}

/** Ask `getTopic` every `ms` until the topic says research is no longer running, then call
 *  `done` (its failures are its own to report). A failed request asks again; an API without
 *  `research_running` counts as done. Returns a function that stops asking. */
export function pollResearch(
  getTopic: () => Promise<{ research_running?: boolean } | null>,
  done: () => void | Promise<void>,
  ms: number = RESEARCH_POLL_MS
): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const tick = async () => {
    const topic = await getTopic().catch(() => null);
    if (stopped) return;
    if (topic && !topic.research_running) {
      stopped = true;
      try {
        await done();
      } catch {
        /* `done` reports its own failures */
      }
      return;
    }
    timer = setTimeout(tick, ms);
  };
  timer = setTimeout(tick, ms);
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}
