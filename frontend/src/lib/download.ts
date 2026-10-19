/** File downloads that fail visibly: fetch, check the status, then save the blob under the
 *  server's filename. A plain `<a download>` link would save an API error body as the file. */

/** The filename from a Content-Disposition header (filename* preferred), else `fallback`.
 *  Only the last path segment is kept. */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  let name: string | null = null;
  const extended = /filename\*\s*=\s*([^']*)'[^']*'([^;]+)/i.exec(header);
  if (extended) {
    try {
      name = decodeURIComponent(extended[2].trim());
    } catch {
      name = null;
    }
  }
  if (!name) {
    const plain = /filename\s*=\s*(?:"([^"]*)"|([^;]+))/i.exec(header);
    name = plain ? (plain[1] ?? plain[2] ?? '').trim() : null;
  }
  const base = name?.split(/[/\\]/).pop()?.trim();
  return base ? base : fallback;
}

/** GET `url` as a file. Throws an Error carrying the API's `detail` when it isn't 2xx. */
export async function fetchDownload(url: string, fallbackName: string): Promise<{ blob: Blob; name: string }> {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === 'string' ? body.detail : null;
    throw new Error(detail ?? `${res.status} ${res.statusText}`);
  }
  const blob = await res.blob();
  return { blob, name: filenameFromDisposition(res.headers.get('content-disposition'), fallbackName) };
}

/** Hand a blob to the browser's own download under `name`. */
export function saveBlob(blob: Blob, name: string): void {
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = name;
  a.style.display = 'none';
  document.body.append(a);
  a.click();
  a.remove();
  // Revoke after the click has been handled; the download keeps its own reference.
  setTimeout(() => URL.revokeObjectURL(href), 10_000);
}
