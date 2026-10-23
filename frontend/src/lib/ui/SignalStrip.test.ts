import { render } from 'svelte/server';
import { describe, expect, it } from 'vitest';
import SignalStrip from './SignalStrip.svelte';

const signals = { grade: 'high', decay: 'lit', calibration: 'unlit', taught: 'unlit', shipped: 'unlit' } as const;

describe('SignalStrip', () => {
  it('keeps the load-bearing slot whether or not the mark shows, so names line up', () => {
    const html = (loadBearing: boolean) =>
      render(SignalStrip, { props: { name: 'KV Cache', signals, verdict: 'solid', loadBearing } }).body.replace(/<!--.*?-->/g, '');
    const on = html(true);
    const off = html(false);
    for (const body of [on, off]) expect(body).toContain('data-testid="load-bearing-slot"');
    expect(on).toMatch(/data-testid="load-bearing-slot"[^>]*>◆</);
    expect(off).not.toMatch(/data-testid="load-bearing-slot"[^>]*>◆</);
  });

  it('lets a long name wrap instead of cutting it off', () => {
    const { body } = render(SignalStrip, {
      props: { name: 'Scaled Dot-Product Attention', signals, verdict: 'verified' }
    });
    const name = body.match(/<span class="([^"]*)" data-testid="signal-name"/)?.[1] ?? '';
    expect(name).toContain('break-words');
    expect(name).not.toContain('truncate');
    expect(body).toContain('Scaled Dot-Product Attention');
  });

  it('draws untested as a hollow ring and verified as a diamond', () => {
    const untested = render(SignalStrip, { props: { name: 'x', signals, verdict: 'untested' } }).body;
    const unverified = render(SignalStrip, { props: { name: 'x', signals, verdict: 'unverified' } }).body;
    expect(untested).toMatch(/data-verdict="untested"[^>]*data-hollow="true"/);
    expect(unverified).toContain('data-verdict="unverified"');
    expect(unverified).not.toContain('data-hollow');
    // Verified is a diamond, so it reads apart from solid's round green without hue.
    const verified = render(SignalStrip, { props: { name: 'x', signals, verdict: 'verified' } }).body;
    const solid = render(SignalStrip, { props: { name: 'x', signals, verdict: 'solid' } }).body;
    expect(verified).toMatch(/data-verdict="verified"[^>]*data-shape="diamond"/);
    expect(solid).toMatch(/data-verdict="solid"[^>]*data-shape="dot"/);
  });
});
