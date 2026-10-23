// Display names for the snake_case kinds the API sends (models.py Sidebar.kind,
// Deliverable.kind). A kind with no name here is still shown as words, never as
// `MATH_REFRESH`-style raw text.

const SIDEBAR_KINDS: Record<string, string> = {
  math_refresh: 'Math refresher',
  reading_list: 'Reading list',
  reference: 'Reference'
};

const DELIVERABLE_KINDS: Record<string, string> = {
  blog: 'Blog post',
  repo: 'Repo',
  model: 'Model',
  talk: 'Talk',
  ablation: 'Ablation study'
};

/** "math_refresh" or "MATH-REFRESH" -> "Math refresh". */
export function humanizeKind(kind: string | null | undefined): string {
  const words = (kind ?? '').replace(/[_-]+/g, ' ').trim().toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : '';
}

export function sidebarKindLabel(kind: string): string {
  return SIDEBAR_KINDS[kind] ?? humanizeKind(kind);
}

export function deliverableKindLabel(kind: string): string {
  return DELIVERABLE_KINDS[kind] ?? humanizeKind(kind);
}
