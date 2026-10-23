import { describe, expect, it, vi } from 'vitest';
import { RESEARCH_PROGRESS, researchFailed, runTopicResearch } from './research';

describe('runTopicResearch', () => {
  it('reports progress and resolves true when research finishes', async () => {
    const status = vi.fn();
    const run = vi.fn().mockResolvedValue({});
    await expect(runTopicResearch(7, status, run)).resolves.toBe(true);
    expect(run).toHaveBeenCalledWith(7);
    expect(status.mock.calls).toEqual([[RESEARCH_PROGRESS]]);
  });

  it("shows the API's reason when research fails", async () => {
    const status = vi.fn();
    const run = vi.fn().mockRejectedValue(new Error('Anthropic did not accept the API key.'));
    await expect(runTopicResearch(7, status, run)).resolves.toBe(false);
    expect(status).toHaveBeenLastCalledWith('Something went wrong: Anthropic did not accept the API key.');
  });
});

describe('researchFailed', () => {
  it('handles a thrown value that is not an Error', () => {
    expect(researchFailed('offline')).toBe('Something went wrong: offline');
  });
});
