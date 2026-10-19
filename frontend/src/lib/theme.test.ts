import { describe, expect, it } from 'vitest';
import {
  THEME_KEY,
  ThemeController,
  type MediaLike,
  type StorageLike,
  type Theme
} from './theme';

/** In-memory localStorage stand-in. */
function memStorage(init: Record<string, string> = {}): StorageLike & { data: Record<string, string> } {
  const data = { ...init };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = String(v);
    },
    removeItem: (k) => {
      delete data[k];
    }
  };
}

/** Throws on every access, like localStorage in some private windows. */
const throwingStorage: StorageLike = {
  getItem: () => {
    throw new Error('SecurityError');
  },
  setItem: () => {
    throw new Error('QuotaExceededError');
  },
  removeItem: () => {
    throw new Error('SecurityError');
  }
};

/** A `(prefers-color-scheme: light)` MediaQueryList stand-in the test can flip. */
function fakeMedia(light: boolean): MediaLike & { flip: (light: boolean) => void } {
  const listeners: ((e: { matches: boolean }) => void)[] = [];
  const m = {
    matches: light,
    addEventListener: (_: 'change', fn: (e: { matches: boolean }) => void) => {
      listeners.push(fn);
    },
    removeEventListener: (_: 'change', fn: (e: { matches: boolean }) => void) => {
      const i = listeners.indexOf(fn);
      if (i >= 0) listeners.splice(i, 1);
    },
    flip(next: boolean) {
      m.matches = next;
      for (const fn of [...listeners]) fn({ matches: next });
    }
  };
  return m;
}

function setup(opts: { storage?: StorageLike | (() => StorageLike); light?: boolean }) {
  const applied: Theme[] = [];
  const media = fakeMedia(opts.light ?? false);
  const storage = opts.storage ?? memStorage();
  const ctl = new ThemeController({
    storage: typeof storage === 'function' ? storage : () => storage,
    media: () => media,
    apply: (t) => applied.push(t)
  });
  return { ctl, media, applied };
}

describe('ThemeController', () => {
  it('follows the system by default (light OS → light)', () => {
    const { ctl, applied } = setup({ light: true });
    ctl.init();
    expect(ctl.choice).toBe('system');
    expect(ctl.resolved).toBe('light');
    expect(applied.at(-1)).toBe('light');
  });

  it('follows the system by default (dark OS → dark)', () => {
    const { ctl, applied } = setup({ light: false });
    ctl.init();
    expect(ctl.choice).toBe('system');
    expect(ctl.resolved).toBe('dark');
    expect(applied.at(-1)).toBe('dark');
  });

  it('a stored manual choice wins over the system', () => {
    const { ctl, applied } = setup({ storage: memStorage({ [THEME_KEY]: 'light' }), light: false });
    ctl.init();
    expect(ctl.choice).toBe('light');
    expect(applied.at(-1)).toBe('light');

    const dark = setup({ storage: memStorage({ [THEME_KEY]: 'dark' }), light: true });
    dark.ctl.init();
    expect(dark.ctl.resolved).toBe('dark');
  });

  it('treats an unknown stored value as "system"', () => {
    const { ctl } = setup({ storage: memStorage({ [THEME_KEY]: 'sepia' }), light: true });
    ctl.init();
    expect(ctl.choice).toBe('system');
    expect(ctl.resolved).toBe('light');
  });

  it('remembers a manual choice', () => {
    const storage = memStorage();
    const { ctl, applied } = setup({ storage, light: false });
    ctl.init();
    ctl.set('light');
    expect(storage.data[THEME_KEY]).toBe('light');
    expect(ctl.resolved).toBe('light');
    expect(applied.at(-1)).toBe('light');
  });

  it('choosing "system" clears the stored override and resolves from the OS', () => {
    const storage = memStorage({ [THEME_KEY]: 'dark' });
    const { ctl, applied } = setup({ storage, light: true });
    ctl.init();
    expect(ctl.resolved).toBe('dark');
    ctl.set('system');
    expect(THEME_KEY in storage.data).toBe(false);
    expect(ctl.choice).toBe('system');
    expect(ctl.resolved).toBe('light');
    expect(applied.at(-1)).toBe('light');
  });

  it('applies an OS change live in system mode', () => {
    const { ctl, media, applied } = setup({ light: false });
    ctl.init();
    media.flip(true);
    expect(ctl.resolved).toBe('light');
    expect(applied.at(-1)).toBe('light');
    media.flip(false);
    expect(ctl.resolved).toBe('dark');
    expect(applied.at(-1)).toBe('dark');
  });

  it('ignores an OS change while a manual choice is set', () => {
    const { ctl, media, applied } = setup({ light: false });
    ctl.init();
    ctl.set('dark');
    const before = applied.length;
    media.flip(true);
    expect(ctl.resolved).toBe('dark');
    expect(applied.length).toBe(before);

    // Back to system: the OS (now light) takes over again, and later flips apply.
    ctl.set('system');
    expect(ctl.resolved).toBe('light');
    media.flip(false);
    expect(ctl.resolved).toBe('dark');
  });

  it('keeps working when localStorage throws on every call', () => {
    const { ctl, media, applied } = setup({ storage: throwingStorage, light: true });
    expect(() => ctl.init()).not.toThrow();
    expect(ctl.choice).toBe('system');
    expect(ctl.resolved).toBe('light');
    expect(() => ctl.set('dark')).not.toThrow();
    expect(ctl.resolved).toBe('dark');
    expect(() => ctl.set('system')).not.toThrow();
    media.flip(false);
    expect(applied.at(-1)).toBe('dark');
  });

  it('keeps working when merely reaching localStorage throws', () => {
    const { ctl } = setup({
      storage: () => {
        throw new Error('SecurityError');
      },
      light: true
    });
    expect(() => ctl.init()).not.toThrow();
    expect(ctl.resolved).toBe('light');
    expect(() => ctl.set('light')).not.toThrow();
    expect(ctl.choice).toBe('light');
  });

  it('falls back to dark with no matchMedia', () => {
    const applied: Theme[] = [];
    const ctl = new ThemeController({
      storage: () => memStorage(),
      media: () => null,
      apply: (t) => applied.push(t)
    });
    ctl.init();
    expect(ctl.resolved).toBe('dark');
    expect(applied).toEqual(['dark']);
  });

  it('notifies a listener with the new state', () => {
    const seen: string[] = [];
    const { ctl } = setup({ light: true });
    ctl.onChange = (s) => seen.push(`${s.choice}:${s.resolved}`);
    ctl.init();
    ctl.set('dark');
    expect(seen).toEqual(['system:light', 'dark:dark']);
  });

  it('init is idempotent: one media listener only', () => {
    const { ctl, media, applied } = setup({ light: false });
    ctl.init();
    ctl.init();
    const before = applied.length;
    media.flip(true);
    expect(applied.length).toBe(before + 1);
  });
});
