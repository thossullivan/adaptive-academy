/** File downloads that fail visibly without buffering the file in the tab.
 *
 *  A plain `<a download>` link would save an API error body as if it were the file; fetching
 *  the file to check its status would hold all of it (a backup can be hundreds of MB) in tab
 *  memory. So: ask the API's cheap check endpoint first, and only then hand the real URL to the
 *  browser, which streams the download to disk under the server's Content-Disposition name. */

/** Resolve when `checkUrl` answers 2xx; otherwise throw an Error carrying the API's `detail`. */
export async function checkExport(checkUrl: string): Promise<void> {
  const res = await fetch(checkUrl);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === 'string' ? body.detail : null;
    throw new Error(detail ?? `${res.status} ${res.statusText}`);
  }
}

/** Hand `url` to the browser's own download manager. */
export function startDownload(url: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.download = '';
  a.style.display = 'none';
  document.body.append(a);
  a.click();
  a.remove();
}
