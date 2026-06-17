/**
 * A deliverable is shippable if there's anything to grade: either a URL (the server
 * best-effort fetches its text for supported hosts) or pasted content — or both.
 */
export function canShip(url: string, content: string): boolean {
  return Boolean(url?.trim() || content?.trim());
}
