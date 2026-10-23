import { describe, expect, it } from 'vitest';
import { deliverableKindLabel, humanizeKind, sidebarKindLabel } from './labels';

describe('kind labels', () => {
  it('names the known sidebar and deliverable kinds', () => {
    expect(sidebarKindLabel('math_refresh')).toBe('Math refresher');
    expect(sidebarKindLabel('reading_list')).toBe('Reading list');
    expect(sidebarKindLabel('reference')).toBe('Reference');
    expect(deliverableKindLabel('blog')).toBe('Blog post');
    expect(deliverableKindLabel('ablation')).toBe('Ablation study');
  });

  it('turns an unknown kind into words, never raw snake case', () => {
    expect(sidebarKindLabel('worked_examples')).toBe('Worked examples');
    expect(deliverableKindLabel('DEMO-VIDEO')).toBe('Demo video');
    expect(humanizeKind('')).toBe('');
    expect(humanizeKind(null)).toBe('');
  });
});
