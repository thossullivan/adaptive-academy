import { beforeEach, describe, expect, it, vi } from 'vitest';
import { checkExport } from './download';

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('checkExport', () => {
  it('resolves when the API says the export can be made', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 })));
    await expect(checkExport('/api/export/check')).resolves.toBeUndefined();
  });

  it("throws the API's detail instead of letting the download save an error body", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'database is not SQLite' }), { status: 500 })
      )
    );
    await expect(checkExport('/api/export/check')).rejects.toThrow('database is not SQLite');
  });

  it('falls back to the status line for a non-JSON error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' }))
    );
    await expect(checkExport('/api/export/check')).rejects.toThrow('502 Bad Gateway');
  });
});
