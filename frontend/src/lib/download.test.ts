import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchDownload, filenameFromDisposition } from './download';

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('filenameFromDisposition', () => {
  it('reads the quoted filename', () => {
    expect(filenameFromDisposition('attachment; filename="adaptive_academy-20261019-120000.db"', 'x')).toBe(
      'adaptive_academy-20261019-120000.db'
    );
  });

  it('prefers the RFC 5987 filename*', () => {
    expect(
      filenameFromDisposition(`attachment; filename="a.json"; filename*=utf-8''b%20c.json`, 'x')
    ).toBe('b c.json');
  });

  it('reads an unquoted filename', () => {
    expect(filenameFromDisposition('attachment; filename=plain.db', 'x')).toBe('plain.db');
  });

  it('falls back when missing, and never returns a path', () => {
    expect(filenameFromDisposition(null, 'fallback.db')).toBe('fallback.db');
    expect(filenameFromDisposition('attachment', 'fallback.db')).toBe('fallback.db');
    expect(filenameFromDisposition('attachment; filename="../../etc/passwd"', 'f.db')).toBe('passwd');
  });
});

describe('fetchDownload', () => {
  it('returns the body and the server filename on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('SQLite format 3\u0000', {
          status: 200,
          headers: { 'content-disposition': 'attachment; filename="adaptive_academy-1.db"' }
        })
      )
    );
    const { blob, name } = await fetchDownload('/api/export/backup', 'backup.db');
    expect(name).toBe('adaptive_academy-1.db');
    expect(await blob.text()).toBe('SQLite format 3\u0000');
  });

  it("throws the API's detail instead of saving an error body", async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'database is not SQLite' }), { status: 500 })
      )
    );
    await expect(fetchDownload('/api/export/backup', 'backup.db')).rejects.toThrow(
      'database is not SQLite'
    );
  });

  it('falls back to the status line for a non-JSON error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>bad gateway</html>', { status: 502, statusText: 'Bad Gateway' }))
    );
    await expect(fetchDownload('/api/export/record', 'r.json')).rejects.toThrow('502 Bad Gateway');
  });
});
