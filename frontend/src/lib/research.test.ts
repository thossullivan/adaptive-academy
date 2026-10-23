import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './api';
import {
  RESEARCH_PROGRESS,
  RESEARCH_RUNNING,
  pollResearch,
  researchAlreadyRunning,
  researchFailed,
  researchTopic,
  runTopicResearch
} from './research';

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

describe('research that is already running', () => {
  it('says so in plain words when the API refuses with a 409', async () => {
    const status = vi.fn();
    const run = vi.fn().mockRejectedValue(new ApiError('topic:7:research is already running; wait for it to finish', 409));
    await expect(researchTopic(7, status, run)).resolves.toBe('running');
    expect(status).toHaveBeenLastCalledWith(RESEARCH_RUNNING);
    expect(RESEARCH_RUNNING).toBe('Research is still running for this topic. This page updates when it finishes.');
    expect(RESEARCH_RUNNING).not.toMatch(/[—–!]/);
    // The boolean form still says research did not finish.
    await expect(runTopicResearch(7, vi.fn(), run)).resolves.toBe(false);
  });

  it("keeps the API's words for other refusals, including research that already ran", async () => {
    const status = vi.fn();
    const done = new ApiError('topic already has a foundation; research runs once per topic', 409);
    await expect(researchTopic(7, status, vi.fn().mockRejectedValue(done))).resolves.toBe('failed');
    expect(status).toHaveBeenLastCalledWith('Something went wrong: topic already has a foundation; research runs once per topic');
    await expect(researchTopic(7, status, vi.fn().mockRejectedValue(new ApiError('Bad gateway', 502)))).resolves.toBe('failed');
    // A plain Error (no status) is never read as running.
    expect(researchAlreadyRunning(new Error('409 Conflict'))).toBe(false);
    expect(researchAlreadyRunning(new ApiError('x', 409))).toBe(true);
  });

  it('keeps String(e) reading "Error: ..." for an API error', () => {
    expect(String(new ApiError('nope', 409))).toBe('Error: nope');
  });
});

describe('pollResearch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('asks every few seconds until research stops running, then calls done once', async () => {
    const answers: ({ research_running: boolean } | null)[] = [
      { research_running: true },
      null,
      { research_running: true },
      { research_running: false }
    ];
    const getTopic = vi.fn(async () => {
      const a = answers.shift();
      if (a === null) throw new Error('offline');
      return a ?? { research_running: false };
    });
    const done = vi.fn();
    pollResearch(getTopic, done, 1000);
    expect(getTopic).not.toHaveBeenCalled();
    for (let i = 0; i < 3; i++) await vi.advanceTimersByTimeAsync(1000);
    expect(done).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    expect(getTopic).toHaveBeenCalledTimes(4);
    expect(done).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(getTopic).toHaveBeenCalledTimes(4);
  });

  it('counts an API without research_running as done, and stops when told', async () => {
    const done = vi.fn();
    pollResearch(async () => ({}), done, 1000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(done).toHaveBeenCalledTimes(1);

    const getTopic = vi.fn(async () => ({ research_running: true }));
    const stop = pollResearch(getTopic, done, 1000);
    await vi.advanceTimersByTimeAsync(2000);
    stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(getTopic).toHaveBeenCalledTimes(2);
    expect(done).toHaveBeenCalledTimes(1);
  });

  it('never leaves a rejected done unhandled', async () => {
    const done = vi.fn().mockRejectedValue(new Error('reload failed'));
    pollResearch(async () => ({ research_running: false }), done, 1000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(done).toHaveBeenCalledTimes(1);
  });
});
