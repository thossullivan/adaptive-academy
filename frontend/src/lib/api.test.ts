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
