import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import Stat from './Stat.svelte';

describe('Stat delta', () => {
  it('reads in percentage points beside a percent value', () => {
    const { body } = render(Stat, {
      props: { label: 'Mean score', value: 66, unit: '%', delta: 13, deltaUnit: 'pts', deltaLabel: 'latest probe against the one before' }
    });
    expect(body).toContain('+13 pts');
    expect(body).toContain('up 13 points, latest probe against the one before');
    expect(body).not.toContain('0.13');
    expect(body).not.toContain('↑');
  });

  it('shows a fraction of a point to one decimal', () => {
    const { body } = render(Stat, { props: { label: 'x', value: 66, delta: 0.6, deltaUnit: 'pts', deltaLabel: 'change in the mean from the latest probe' } });
    expect(body).toContain('+0.6 pts');
    expect(body).toContain('up 0.6 points, change in the mean from the latest probe');
  });

  it('signs a drop and a flat change', () => {
    expect(render(Stat, { props: { label: 'x', value: 1, delta: -4, deltaUnit: 'pts' } }).body).toContain('−4 pts');
    expect(render(Stat, { props: { label: 'x', value: 1, delta: 0, deltaUnit: 'pts' } }).body).toContain('±0 pts');
  });

  it('keeps the arrow form by default', () => {
    const { body } = render(Stat, { props: { label: 'x', value: 1, delta: 0.25 } });
    expect(body).toContain('↑');
    expect(body).toContain('0.25');
  });
});
