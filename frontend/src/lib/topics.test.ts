import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Topic } from './types';

const { api } = vi.hoisted(() => ({
  api: {
    listTopics: vi.fn(),
    getTopic: vi.fn(),
    deleteTopic: vi.fn(),
    deleteDemo: vi.fn()
  }
}));
vi.mock('./api', () => ({ api }));

import { topics } from './topics.svelte';

const topic = (id: number, conceptIds: number[]): Topic => ({
  id,
  title: `T${id}`,
  concepts: conceptIds.map((c) => ({ id: c, name: `c${c}`, is_load_bearing: false }))
});

describe('deleting a topic', () => {
  let data: Record<string, string>;

  beforeEach(() => {
    data = {};
    vi.stubGlobal('window', {
      sessionStorage: {
        getItem: (k: string) => data[k] ?? null,
        setItem: (k: string, v: string) => void (data[k] = v),
        removeItem: (k: string) => void delete data[k]
      }
    });
    for (const fn of Object.values(api)) fn.mockReset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("clears the note drafts of the topic's concepts, from the list and a fresh fetch, and no others", async () => {
    topics.list = [topic(1, [10, 11]), topic(2, [20])];
    // A concept made after the list loaded is in the fresh copy only.
    api.getTopic.mockResolvedValue(topic(1, [10, 11, 12]));
    api.deleteTopic.mockResolvedValue({});
    api.listTopics.mockResolvedValue([topic(2, [20])]);
    for (const id of [10, 11, 12, 20]) data[`aa.note-draft.${id}`] = `draft ${id}`;

    await topics.remove(1);

    expect(api.deleteTopic).toHaveBeenCalledWith(1);
    expect(Object.keys(data)).toEqual(['aa.note-draft.20']);
    expect(topics.list.map((t) => t.id)).toEqual([2]);
  });

  it('keeps the drafts when the delete fails, and still clears the listed ones when the fresh fetch fails', async () => {
    topics.list = [topic(1, [10])];
    api.getTopic.mockRejectedValue(new Error('offline'));
    api.deleteTopic.mockRejectedValueOnce(new Error('500'));
    data['aa.note-draft.10'] = 'draft';

    await expect(topics.remove(1)).rejects.toThrow('500');
    expect(data['aa.note-draft.10']).toBe('draft');

    api.deleteTopic.mockResolvedValue({});
    api.listTopics.mockResolvedValue([]);
    await topics.remove(1);
    expect(data).toEqual({});
  });

  it('clears the drafts of the removed demo through its own route', async () => {
    topics.list = [topic(3, [30])];
    api.getTopic.mockResolvedValue(topic(3, [30]));
    api.deleteDemo.mockResolvedValue({});
    api.listTopics.mockResolvedValue([]);
    data['aa.note-draft.30'] = 'draft';

    await topics.remove(3, api.deleteDemo);

    expect(api.deleteDemo).toHaveBeenCalledWith(3);
    expect(api.deleteTopic).not.toHaveBeenCalled();
    expect(data).toEqual({});
  });
});
