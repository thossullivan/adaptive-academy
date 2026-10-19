import { browser } from '$app/environment';
import { LIGHT_QUERY, ThemeController, type Theme, type ThemeChoice } from './theme';

/** Reactive theme state for the UI. The logic lives in theme.ts; app.html sets the initial
 *  `data-theme` before hydration so there is no flash of the wrong theme. */
class ThemeStore {
  /** What the learner picked ('system' follows the OS). */
  choice = $state<ThemeChoice>('system');
  /** The theme actually applied. */
  current = $state<Theme>('dark');

  private ctl = new ThemeController({
    storage: () => (browser ? window.localStorage : null),
    media: () => (browser && typeof window.matchMedia === 'function' ? window.matchMedia(LIGHT_QUERY) : null),
    apply: (t) => {
      if (browser) document.documentElement.setAttribute('data-theme', t);
    }
  });

  constructor() {
    this.ctl.onChange = (s) => {
      this.choice = s.choice;
      this.current = s.resolved;
    };
  }

  init() {
    this.ctl.init();
  }

  set(choice: ThemeChoice) {
    this.ctl.set(choice);
  }
}

export const theme = new ThemeStore();
