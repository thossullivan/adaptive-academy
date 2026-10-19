// Theme logic, kept free of Svelte and the DOM so it is unit-testable (see theme.test.ts).
// The reactive wrapper is theme.svelte.ts; the pre-hydration copy of `resolve` is the inline
// script in app.html — keep the three in step.

export type Theme = 'dark' | 'light';
/** What the learner picked: follow the OS, or a fixed theme. */
export type ThemeChoice = 'system' | Theme;

export const THEME_KEY = 'aa-theme';
/** Matches when the OS asks for light; anything else (dark, no preference) resolves to dark. */
export const LIGHT_QUERY = '(prefers-color-scheme: light)';
export const THEME_CHOICES: ThemeChoice[] = ['system', 'light', 'dark'];

export type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export interface MediaLike {
  matches: boolean;
  addEventListener(type: 'change', fn: (e: { matches: boolean }) => void): void;
  removeEventListener(type: 'change', fn: (e: { matches: boolean }) => void): void;
}

export interface ThemeEnv {
  /** May throw (some private windows deny localStorage outright). */
  storage: () => StorageLike | null;
  media: () => MediaLike | null;
  apply: (theme: Theme) => void;
}

export interface ThemeState {
  choice: ThemeChoice;
  resolved: Theme;
}

export function resolve(choice: ThemeChoice, osLight: boolean): Theme {
  if (choice === 'system') return osLight ? 'light' : 'dark';
  return choice;
}

export class ThemeController {
  choice: ThemeChoice = 'system';
  resolved: Theme = 'dark';
  onChange: ((s: ThemeState) => void) | null = null;

  private media: MediaLike | null = null;
  private listening = false;

  constructor(private env: ThemeEnv) {}

  init() {
    this.choice = this.readChoice();
    if (!this.listening) {
      try {
        this.media = this.env.media();
        this.media?.addEventListener('change', this.onMediaChange);
      } catch {
        this.media = null;
      }
      this.listening = true;
    }
    this.update();
  }

  set(choice: ThemeChoice) {
    this.choice = choice;
    this.withStorage((s) => {
      if (choice === 'system') s.removeItem(THEME_KEY);
      else s.setItem(THEME_KEY, choice);
    });
    this.update();
  }

  private onMediaChange = () => {
    if (this.choice === 'system') this.update();
  };

  private update() {
    this.resolved = resolve(this.choice, this.media?.matches ?? false);
    this.env.apply(this.resolved);
    this.onChange?.({ choice: this.choice, resolved: this.resolved });
  }

  private readChoice(): ThemeChoice {
    const stored = this.withStorage((s) => s.getItem(THEME_KEY));
    return stored === 'light' || stored === 'dark' ? stored : 'system';
  }

  private withStorage<T>(fn: (s: StorageLike) => T): T | null {
    try {
      const s = this.env.storage();
      return s ? fn(s) : null;
    } catch {
      // Storage unavailable: the choice still applies for this page, it just isn't remembered.
      return null;
    }
  }
}
