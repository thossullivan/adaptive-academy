import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { VERDICT_COLOR, VERDICT_HOLLOW, VERDICT_LABEL, VERDICT_SHAPE, VERDICT_TEXT_COLOR, type Verdict } from './competence';

// The verdict colours live in app.css (one set per theme) and are named in competence.ts.
// These checks keep the two in step and hold the contrast the comments in app.css promise.

const css = readFileSync(new URL('../app.css', import.meta.url), 'utf8');

/** The `--name: #hex` declarations of the block that starts with `selector`. */
function themeTokens(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  expect(start, `${selector} block in app.css`).toBeGreaterThanOrEqual(0);
  const body = css.slice(start, css.indexOf('\n}', start));
  return Object.fromEntries([...body.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]));
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const THEMES = { dark: themeTokens(":root,\n[data-theme='dark']"), light: themeTokens("[data-theme='light']") };
const varName = (ref: string) => ref.match(/var\(--([a-z0-9-]+)\)/)![1];

describe('verdict colours', () => {
  it('"verified" has its own token, not the brand accent primary buttons use', () => {
    expect(VERDICT_COLOR.verified).toBe('var(--verdict-verified)');
    expect(VERDICT_TEXT_COLOR.verified).toBe('var(--verdict-verified)');
    for (const v of Object.keys(VERDICT_COLOR) as Verdict[]) expect(VERDICT_COLOR[v]).not.toBe('var(--accent)');
  });

  it('only "untested" is drawn hollow', () => {
    expect((Object.keys(VERDICT_HOLLOW) as Verdict[]).filter((v) => VERDICT_HOLLOW[v])).toEqual(['untested']);
    expect(Object.keys(VERDICT_HOLLOW).sort()).toEqual(Object.keys(VERDICT_LABEL).sort());
    expect(Object.keys(VERDICT_SHAPE).sort()).toEqual(Object.keys(VERDICT_LABEL).sort());
  });

  it('marks that are close in colour differ in shape, so hue is never the only cue', () => {
    // Two greys (untested, unverified) and teal beside green (verified, solid; closest in
    // light, where both are dark tones).
    expect(VERDICT_SHAPE.untested).not.toBe(VERDICT_SHAPE.unverified);
    expect(VERDICT_SHAPE.verified).not.toBe(VERDICT_SHAPE.solid);
    expect(VERDICT_SHAPE.verified).toBe('diamond');
  });

  for (const [theme, t] of Object.entries(THEMES)) {
    it(`${theme}: every verdict word is at least 4.5:1 on bg, surface and surface-2`, () => {
      for (const v of Object.keys(VERDICT_TEXT_COLOR) as Verdict[]) {
        const fg = t[varName(VERDICT_TEXT_COLOR[v])];
        expect(fg, `${theme} --${varName(VERDICT_TEXT_COLOR[v])}`).toBeTruthy();
        for (const bg of ['bg', 'surface', 'surface-2']) {
          expect(contrast(fg, t[bg]), `${v} on ${bg} (${theme})`).toBeGreaterThanOrEqual(4.5);
        }
      }
    });

    it(`${theme}: the hollow "untested" ring is at least 3:1 (a graphic) on bg and surface`, () => {
      for (const bg of ['bg', 'surface']) {
        expect(contrast(t['verdict-untested'], t[bg]), `untested ring on ${bg}`).toBeGreaterThanOrEqual(3);
      }
    });

    it(`${theme}: every filled mark is at least 3:1 (a graphic) on bg and surface`, () => {
      for (const v of (Object.keys(VERDICT_COLOR) as Verdict[]).filter((v) => !VERDICT_HOLLOW[v])) {
        const fill = t[varName(VERDICT_COLOR[v])];
        for (const bg of ['bg', 'surface']) {
          expect(contrast(fill, t[bg]), `${v} mark on ${bg} (${theme})`).toBeGreaterThanOrEqual(3);
        }
      }
    });

    it(`${theme}: "verified" teal is not the accent, the success green or the info blue`, () => {
      for (const other of ['accent', 'success', 'info']) {
        expect(t['verdict-verified'].toLowerCase()).not.toBe(t[other].toLowerCase());
      }
    });
  }
});
