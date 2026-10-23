// Running topic research from the UI. Shared by the new-topic page and the Sources page's
// "Research again", so both say the same thing while it runs and when it fails.
import { api } from './api';

export const RESEARCH_PROGRESS = 'Finding sources. This can take a moment…';

/** The line shown when research (or creating its topic) fails. The API's own detail says
 *  how to fix it, e.g. "Anthropic did not accept the API key…". */
export function researchFailed(e: unknown): string {
  return 'Something went wrong: ' + (e instanceof Error ? e.message : String(e));
}

/** Run research for `topicId`, reporting progress and any failure through `status`.
 *  Resolves true when research finished. */
export async function runTopicResearch(
  topicId: number,
  status: (text: string) => void,
  run: (topicId: number) => Promise<unknown> = api.runResearch
): Promise<boolean> {
  status(RESEARCH_PROGRESS);
  try {
    await run(topicId);
    return true;
  } catch (e) {
    status(researchFailed(e));
    return false;
  }
}
