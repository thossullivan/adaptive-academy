import { describe, expect, it, vi } from 'vitest';
import { api } from './api';

describe('api.sendMessage', () => {
  it('posts content and returns the parsed result', async () => {
    const result = {
      reply: 'Hint: try first', attempt_logged: false,
      assistance_level: 'low', challenge_level: 'high', events: []
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => result } as Response);

    const out = await api.sendMessage(1, 'answer please');

    expect(global.fetch).toHaveBeenCalledWith('/api/conversations/1/messages', expect.objectContaining({ method: 'POST' }));
    expect(out.reply).toBe('Hint: try first');
  });
});

describe('research api client', () => {
  it('createTopic posts intent and returns topic', async () => {
    const topic = { id: 1, title: 'LLMs', concepts: [] };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => topic }) as any;
    const out = await api.createTopic({ title: 'LLMs', goal: 'learn' });
    expect(out.id).toBe(1);
    expect((global.fetch as any).mock.calls[0][0]).toBe('/api/topics');
    expect((global.fetch as any).mock.calls[0][1].method).toBe('POST');
  });

  it('reviewSources posts accepted/pruned ids', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [] }) as any;
    await api.reviewSources(3, [1], [2]);
    const [url, opts] = (global.fetch as any).mock.calls[0];
    expect(url).toBe('/api/topics/3/sources/review');
    expect(JSON.parse(opts.body)).toEqual({ accepted_ids: [1], pruned_ids: [2] });
  });
});

describe('curriculum api client', () => {
  it('generateCurriculum posts to the curriculum endpoint', async () => {
    const cur = { track: { id: 1, title: 'T', overview: 'ov' }, phases: [], sidebars: [], concepts: [], events: [] };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => cur }) as any;
    const out = await api.generateCurriculum(1);
    expect((global.fetch as any).mock.calls[0][0]).toBe('/api/topics/1/curriculum');
    expect((global.fetch as any).mock.calls[0][1].method).toBe('POST');
    expect(out.track.overview).toBe('ov');
  });

  it('updateItem patches the item status', async () => {
    const item = { id: 5, text: 'x', type: 'read', status: 'done', position: 0 };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => item }) as any;
    const out = await api.updateItem(5, { status: 'done' });
    const [url, opts] = (global.fetch as any).mock.calls[0];
    expect(url).toBe('/api/items/5');
    expect(opts.method).toBe('PATCH');
    expect(JSON.parse(opts.body)).toEqual({ status: 'done' });
    expect(out.status).toBe('done');
  });
});
