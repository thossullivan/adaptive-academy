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

describe('assessor api client', () => {
  it('assess posts the probe and returns the assessment', async () => {
    const assessment = {
      id: 7, kind: 'self_explanation', prompt: 'p', response: 'r', verdict: 'weak',
      score: 0.3, gaps: ['vague'], confidence_predicted: null, confidence_actual: null,
      delta: null, estimate_level: 'low'
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => assessment }) as any;
    const out = await api.assess(1, { kind: 'self_explanation', response: 'r' });
    const [url, opts] = (global.fetch as any).mock.calls[0];
    expect(url).toBe('/api/concepts/1/assess');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ kind: 'self_explanation', response: 'r' });
    expect(out.estimate_level).toBe('low');
  });

  it('gradeCard posts the result and returns the card', async () => {
    const card = {
      id: 2, concept_id: 1, front: 'f', back: 'b', status: 'active',
      interval: 1, reps: 1, last_result: 'good'
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => card }) as any;
    const out = await api.gradeCard(2, 'good');
    const [url, opts] = (global.fetch as any).mock.calls[0];
    expect(url).toBe('/api/retention/cards/2/grade');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ result: 'good' });
    expect(out.reps).toBe(1);
  });

  it('remediate posts to the concept remediate endpoint and returns items', async () => {
    const remediation = {
      items: [{ id: 9, text: 'x', type: 'read', status: 'todo', position: 0, is_remediation: true }],
      events: []
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => remediation }) as any;
    const out = await api.remediate(4, 7);
    const [url, opts] = (global.fetch as any).mock.calls[0];
    expect(url).toBe('/api/concepts/4/remediate');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ from_assessment_id: 7 });
    expect(out.items[0].is_remediation).toBe(true);
  });
});

describe('anchor api client', () => {
  it('generateAnchors posts to the topic anchors endpoint and returns anchors', async () => {
    const gen = {
      anchors: [{ id: 1, source_doc_id: 2, concept_id: 3, question: 'q', reference_answer: 'a', key_points: [] }],
      events: []
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => gen }) as any;
    const out = await api.generateAnchors(7);
    const [url, opts] = (global.fetch as any).mock.calls[0];
    expect(url).toBe('/api/topics/7/anchors');
    expect(opts.method).toBe('POST');
    expect(out.anchors[0].question).toBe('q');
  });

  it('listConceptAnchors gets the concept anchors endpoint and returns anchors', async () => {
    const anchors = [{ id: 1, source_doc_id: 2, concept_id: 4, question: 'q', reference_answer: 'a', key_points: ['k'] }];
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => anchors }) as any;
    const out = await api.listConceptAnchors(4);
    expect((global.fetch as any).mock.calls[0][0]).toBe('/api/concepts/4/anchors');
    expect(out[0].key_points).toEqual(['k']);
  });
});
