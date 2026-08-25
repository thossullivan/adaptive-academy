import type { MemoryHit, MemoryReindexBody, MemoryReindexResult, MemorySearchResult } from '$lib/types';

export const MAX_MEMORY_RESULTS = 50;
export const DEFAULT_MEMORY_RESULTS = 20;
export const REINDEX_FAILURE_TOAST = 'Memory reindex failed.';

interface SearchOptions {
  topic_id: number;
  k: number;
}

type SearchMemory = (query: string, options: SearchOptions) => Promise<MemorySearchResult>;
type ReindexMemory = (body: MemoryReindexBody) => Promise<MemoryReindexResult>;
type ShowToast = (message: string, tone?: 'success' | 'error') => void;

export interface SearchOutcome {
  hits: MemoryHit[];
  k: number;
}

export function clampMemoryResultLimit(value: string): number {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed)
    ? Math.min(MAX_MEMORY_RESULTS, Math.max(1, parsed))
    : DEFAULT_MEMORY_RESULTS;
}

export async function runMemorySearch(
  searchMemory: SearchMemory,
  query: string,
  topicId: number,
  resultLimit: string
): Promise<SearchOutcome> {
  const k = clampMemoryResultLimit(resultLimit);
  const result = await searchMemory(query.trim(), { topic_id: topicId, k });
  return { hits: result.hits, k };
}

export function reindexSuccessToast(result: MemoryReindexResult): string {
  const prefix = result.truncated ? 'Reindex stopped at the time limit' : 'Reindex complete';
  return `${prefix}: ${result.indexed} indexed, ${result.skipped} skipped, ${result.removed} removed.`;
}

export async function runMemoryReindex(
  reindexMemory: ReindexMemory,
  body: MemoryReindexBody,
  showToast: ShowToast
): Promise<MemoryReindexResult> {
  try {
    const result = await reindexMemory(body);
    showToast(reindexSuccessToast(result));
    return result;
  } catch (error) {
    showToast(REINDEX_FAILURE_TOAST, 'error');
    throw error;
  }
}
