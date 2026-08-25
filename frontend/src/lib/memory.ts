import type { MemoryHit } from './types';

const KIND_ORDER = [
  'vault_note',
  'source_doc',
  'learner_output',
  'tutor_turn',
  'question'
] as const;

export interface MemoryGroup {
  kind: string;
  hits: MemoryHit[];
}

export function groupByKind(hits: MemoryHit[]): MemoryGroup[] {
  const grouped = new Map<string, MemoryHit[]>();
  for (const hit of hits) {
    const group = grouped.get(hit.kind) ?? [];
    group.push(hit);
    grouped.set(hit.kind, group);
  }

  const known = KIND_ORDER.flatMap((kind) => {
    const group = grouped.get(kind);
    return group ? [{ kind, hits: group }] : [];
  });
  const unknown = [...grouped.entries()]
    .filter(([kind]) => !KIND_ORDER.some((knownKind) => knownKind === kind))
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([kind, group]) => ({ kind, hits: group }));
  return [...known, ...unknown];
}

export function trimSnippet(text: string, maxLength = 240): string {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) return normalized;
  if (maxLength <= 0) return '';
  if (maxLength === 1) return '…';
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}
