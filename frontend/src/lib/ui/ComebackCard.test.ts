import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import ComebackCard from './ComebackCard.svelte';

const wind = {
  topic_id: 1, topic_title: 't', value: 0, state: 'unsailed', last_sailed: null,
  days_since: null, progress: 0
};
const LONG =
  "Derive the evidence lower bound by hand from Jensen's inequality, then implement a " +
  'reparameterised Gaussian VAE on MNIST and verify the gradient estimator against finite ' +
  'differences before scaling to the full dataset.';

const move = (label: string) => ({ move: { kind: 'build', label, href: '/topics/1/track', minutes: 25 } });

describe('ComebackCard', () => {
  it('clips a long move on a word boundary with an ellipsis and keeps the full text reachable', () => {
    const { body } = render(ComebackCard, { props: { wind, comeback: move(LONG) } });
    // clipped on a word boundary with a visible ellipsis
    const shown = body.match(/>\s*(Derive[^<]*…)/)?.[1];
    expect(shown, 'the clipped move').toBeTruthy();
    expect(shown!.length).toBeLessThanOrEqual(120);
    expect(LONG.startsWith(shown!.slice(0, -1))).toBe(true);
    expect(LONG[shown!.length - 1]).toBe(' '); // the next char in the full text is a space
    // the full text is reachable: on hover (title) and via a disclosure button
    expect(body).toContain('full dataset.');
    expect(body).toMatch(/title="Derive[^"]*full dataset\."/);
    expect(body).toContain('aria-expanded="false"');
    expect(body).toContain('Show all');
  });

  it('shows a short move whole, with no disclosure', () => {
    const { body } = render(ComebackCard, { props: { wind, comeback: move('derive the gradient') } });
    expect(body).toContain('derive the gradient');
    expect(body).not.toContain('…');
    expect(body).not.toContain('Show all');
  });
});
