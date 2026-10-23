import { describe, expect, it, vi } from 'vitest';
import { NoteConflictError, api } from './api';

describe('api.sendMessage', () => {
  it('posts content and returns the parsed result', async () => {
    const result = {
      reply: 'Hint: try first', attempt_logged: false,
      assistance_level: 'low', challenge_level: 'high', events: []
    };
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => result } as Response);

    const out = await api.sendMessage(1, 'answer please');

    expect(globalThis.fetch).toHaveBeenCalledWith('/api/conversations/1/messages', expect.objectContaining({ method: 'POST' }));
    expect(JSON.parse((globalThis.fetch as any).mock.calls[0][1].body)).toEqual({ content: 'answer please', attempt: false });
    expect(out.reply).toBe('Hint: try first');
  });

  it('marks a Submit attempt send as an attempt', async () => {
    const result = {
      reply: 'Good start', attempt_logged: true, attempt_outcome: 'accepted',
      assistance_level: 'low', challenge_level: 'high', events: [], memory: []
    };
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => result } as Response);

    const out = await api.sendMessage(1, 'I divide by sqrt(d_k) because...', true);

    expect(JSON.parse((globalThis.fetch as any).mock.calls[0][1].body)).toEqual({
      content: 'I divide by sqrt(d_k) because...', attempt: true
    });
    expect(out.attempt_outcome).toBe('accepted');
  });
});

describe('research api client', () => {
  it('createTopic posts intent and returns topic', async () => {
    const topic = { id: 1, title: 'LLMs', concepts: [] };
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => topic }) as any;
    const out = await api.createTopic({ title: 'LLMs', goal: 'learn' });
    expect(out.id).toBe(1);
    expect((globalThis.fetch as any).mock.calls[0][0]).toBe('/api/topics');
    expect((globalThis.fetch as any).mock.calls[0][1].method).toBe('POST');
  });

  it('reviewSources posts accepted/pruned ids', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [] }) as any;
    await api.reviewSources(3, [1], [2]);
    const [url, opts] = (globalThis.fetch as any).mock.calls[0];
    expect(url).toBe('/api/topics/3/sources/review');
    expect(JSON.parse(opts.body)).toEqual({ accepted_ids: [1], pruned_ids: [2] });
  });
});

describe('curriculum api client', () => {
  it('generateCurriculum posts to the curriculum endpoint', async () => {
    const cur = { track: { id: 1, title: 'T', overview: 'ov' }, phases: [], sidebars: [], concepts: [], events: [] };
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => cur }) as any;
    const out = await api.generateCurriculum(1);
    expect((globalThis.fetch as any).mock.calls[0][0]).toBe('/api/topics/1/curriculum');
    expect((globalThis.fetch as any).mock.calls[0][1].method).toBe('POST');
    expect(out.track.overview).toBe('ov');
  });

  it('updateItem patches the item status', async () => {
    const item = { id: 5, text: 'x', type: 'read', status: 'done', position: 0 };
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => item }) as any;
    const out = await api.updateItem(5, { status: 'done' });
    const [url, opts] = (globalThis.fetch as any).mock.calls[0];
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
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => assessment }) as any;
    const out = await api.assess(1, { kind: 'self_explanation', response: 'r' });
    const [url, opts] = (globalThis.fetch as any).mock.calls[0];
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
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => card }) as any;
    const out = await api.gradeCard(2, 'good');
    const [url, opts] = (globalThis.fetch as any).mock.calls[0];
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
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => remediation }) as any;
    const out = await api.remediate(4, 7);
    const [url, opts] = (globalThis.fetch as any).mock.calls[0];
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
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => gen }) as any;
    const out = await api.generateAnchors(7);
    const [url, opts] = (globalThis.fetch as any).mock.calls[0];
    expect(url).toBe('/api/topics/7/anchors');
    expect(opts.method).toBe('POST');
    expect(out.anchors[0].question).toBe('q');
  });

  it('listConceptAnchors gets the concept anchors endpoint and returns anchors', async () => {
    const anchors = [{ id: 1, source_doc_id: 2, concept_id: 4, question: 'q', reference_answer: 'a', key_points: ['k'] }];
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => anchors }) as any;
    const out = await api.listConceptAnchors(4);
    expect((globalThis.fetch as any).mock.calls[0][0]).toBe('/api/concepts/4/anchors');
    expect(out[0].key_points).toEqual(['k']);
  });
});

describe('memory api client', () => {
  it('searchMemory constructs all supported query parameters', async () => {
    const result = { hits: [] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
    vi.stubGlobal('fetch', fetchMock);

    const out = await api.searchMemory('working memory', {
      topic_id: 7,
      concept_id: 9,
      kinds: ['vault_note', 'source_doc'],
      k: 20
    });

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/memory/search?q=working+memory&topic_id=7&concept_id=9&kinds=vault_note%2Csource_doc&k=20'
    );
    expect(out).toEqual(result);
  });

  it('reindexMemory posts the request and returns counts', async () => {
    const result = { indexed: 3, skipped: 4, removed: 1, truncated: false, ms: 25 };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
    vi.stubGlobal('fetch', fetchMock);

    const out = await api.reindexMemory({ topic_id: 7, vault_path: '/vault' });

    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/memory/reindex');
    expect(opts).toEqual({
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ topic_id: 7, vault_path: '/vault' })
    });
    expect(out).toEqual(result);
  });

  it('memoryStats requests topic stats and returns the response', async () => {
    const result = { by_kind: { vault_note: 3 }, last_indexed_at: null, retriever: 'fts' };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => result });
    vi.stubGlobal('fetch', fetchMock);

    const out = await api.memoryStats(7);

    expect(fetchMock.mock.calls[0][0]).toBe('/api/memory/stats?topic_id=7');
    expect(out).toEqual(result);
  });
});

describe('program api client', () => {
  it('createProgram posts the body and returns the program', async () => {
    const program = { id: 1, title: 'PhD prep', goal_statement: 'g', status: 'draft', milestone_count: 0 };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => program });
    vi.stubGlobal('fetch', fetchMock);
    const out = await api.createProgram({ title: 'PhD prep' });
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/programs');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ title: 'PhD prep' });
    expect(out.id).toBe(1);
  });

  it('acceptProgram posts accepted/pruned link ids', async () => {
    const detail = { program: { id: 1, title: 't', goal_statement: 'g', status: 'active', milestone_count: 1 }, milestones: [] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => detail });
    vi.stubGlobal('fetch', fetchMock);
    await api.acceptProgram(1, [2], [3]);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/programs/1/accept');
    expect(JSON.parse(opts.body)).toEqual({ accepted_link_ids: [2], pruned_link_ids: [3] });
  });

  it('overrideGate posts the reason', async () => {
    const milestone = { id: 1, title: 't', success_criteria: 'sc', order_index: 0, gate_status: 'overridden', depends_on: [], override_reason: 'time-boxed', links: [] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => milestone });
    vi.stubGlobal('fetch', fetchMock);
    const out = await api.overrideGate(1, 2, 'time-boxed');
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/programs/1/milestones/2/override');
    expect(JSON.parse(opts.body)).toEqual({ reason: 'time-boxed' });
    expect(out.gate_status).toBe('overridden');
  });

  it('programContext returns null for a standalone topic (200 + null body)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => null });
    vi.stubGlobal('fetch', fetchMock);
    const out = await api.programContext(5);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/topics/5/program-context');
    expect(out).toBeNull();
  });

  it('programContext throws on a 404 (unknown topic id)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false, status: 404, statusText: 'Not Found', json: async () => ({ detail: 'topic not found' })
    });
    vi.stubGlobal('fetch', fetchMock);
    await expect(api.programContext(5)).rejects.toThrow('topic not found');
  });

  it('programContext returns the context when present', async () => {
    const ctx = { program_id: 1, program_title: 'p', milestone_id: 2, milestone_title: 'm', gate_status: 'open', unverified: ['x'] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ctx });
    vi.stubGlobal('fetch', fetchMock);
    const out = await api.programContext(5);
    expect(out).toEqual(ctx);
  });
});

describe('api errors', () => {
  it('surfaces the API detail message instead of the bare status', async () => {
    const detail = 'No ANTHROPIC_API_KEY configured — copy .env.example to .env.';
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail }), { status: 503, statusText: 'Service Unavailable' })
    ) as any;
    await expect(api.listTopics()).rejects.toThrow(detail);
  });

  it('falls back to the status line when the body has no detail', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response('<html>oops</html>', { status: 500, statusText: 'Internal Server Error' })
    ) as any;
    await expect(api.listTopics()).rejects.toThrow('500 Internal Server Error');
  });
});

describe('api.saveNote', () => {
  const saved = { concept_id: 3, body: 'mine', updated_at: '2026-10-22T09:00:00' };

  it('sends the version it was written on only when given', async () => {
    globalThis.fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify(saved), { status: 200 })) as any;
    await api.saveNote(3, 'mine');
    await api.saveNote(3, 'mine', '/v', null);
    await api.saveNote(3, 'mine', '', '2026-10-22T09:00:00');
    const bodies = (globalThis.fetch as any).mock.calls.map((c: any[]) => JSON.parse(c[1].body));
    expect(bodies).toEqual([
      { body: 'mine', vault_path: '' },
      { body: 'mine', vault_path: '/v', base_updated_at: null },
      { body: 'mine', vault_path: '', base_updated_at: '2026-10-22T09:00:00' }
    ]);
  });

  it('turns a 409 into NoteConflictError carrying the note saved now', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Saved somewhere else.', note: { ...saved, body: 'theirs' } }), { status: 409 })
    ) as any;
    const err = await api.saveNote(3, 'mine', '', '2026-10-22T08:00:00').catch((e) => e);
    expect(err).toBeInstanceOf(NoteConflictError);
    expect(err.message).toBe('Saved somewhere else.');
    expect(err.note.body).toBe('theirs');
  });
});

describe('demo api client', () => {
  it('createDemo posts to /api/demo and returns the topic id', async () => {
    globalThis.fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({ topic_id: 7, created: true }) }) as any;
    const out = await api.createDemo();
    const [url, opts] = (globalThis.fetch as any).mock.calls[0];
    expect(url).toBe('/api/demo');
    expect(opts.method).toBe('POST');
    expect(out).toEqual({ topic_id: 7, created: true });
  });

  it('deleteDemo deletes the named demo and treats an already-removed one as done', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'topic not found' }), { status: 404 })
    ) as any;
    await expect(api.deleteDemo(42)).resolves.toBeUndefined();
    const [url, opts] = (globalThis.fetch as any).mock.calls[0];
    expect(url).toBe('/api/demo/42');
    expect(opts.method).toBe('DELETE');
  });

  it('deleteDemo surfaces a refusal for a topic that is not the demo', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'topic 3 is not a demo topic' }), { status: 400 })
    ) as any;
    await expect(api.deleteDemo(3)).rejects.toThrow('not a demo topic');
  });

  it('deleteDemo surfaces a real failure', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'boom' }), { status: 500 })
    ) as any;
    await expect(api.deleteDemo(7)).rejects.toThrow('boom');
  });
});
