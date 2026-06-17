import { browser } from '$app/environment';

type Theme = 'dark' | 'light';

function read(): Theme {
  if (!browser) return 'dark';
  const t = localStorage.getItem('aa-theme');
  return t === 'light' ? 'light' : 'dark';
}

class ThemeStore {
  current = $state<Theme>('dark');

  init() {
    this.current = read();
    this.apply();
  }

  private apply() {
    if (!browser) return;
    document.documentElement.setAttribute('data-theme', this.current);
  }

  toggle() {
    this.current = this.current === 'dark' ? 'light' : 'dark';
    if (browser) localStorage.setItem('aa-theme', this.current);
    this.apply();
  }
}

export const theme = new ThemeStore();
