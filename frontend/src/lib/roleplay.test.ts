import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from './api';

beforeEach(() => { vi.restoreAllMocks(); });

describe('roleplay api', () => {
  it('startRoleplay POSTs to the milestone roleplay endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ session_id: 5, status: 'active', brief_public: {}, turns: [] }),
                   { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const out = await api.startRoleplay(2, 9);
    expect(out.session_id).toBe(5);
    expect(fetchMock.mock.calls[0][0]).toContain('/api/programs/2/milestones/9/roleplay');
  });

  it('sendRoleplayTurn posts content', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ reply: 'hi', status: 'active' }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const out = await api.sendRoleplayTurn(5, 'hello');
    expect(out.reply).toBe('hi');
    expect(fetchMock.mock.calls[0][0]).toContain('/api/roleplay/5/turns');
  });
});
