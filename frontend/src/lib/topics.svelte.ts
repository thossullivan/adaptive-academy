import { browser } from '$app/environment';
import { api } from './api';
import type { Topic } from './types';

const KEY = 'aa-current-topic';

class TopicStore {
  list = $state<Topic[]>([]);
  currentId = $state<number | null>(null);
  loaded = $state(false);

  current = $derived(this.list.find((t) => t.id === this.currentId) ?? this.list[0] ?? null);

  async load() {
    this.list = await api.listTopics();
    const saved = browser ? Number(localStorage.getItem(KEY)) : NaN;
    if (saved && this.list.some((t) => t.id === saved)) {
      this.currentId = saved;
    } else if (this.list.length) {
      this.currentId = this.list[0].id;
    }
    this.loaded = true;
  }

  select(id: number) {
    this.currentId = id;
    if (browser) localStorage.setItem(KEY, String(id));
  }

  /** Re-fetch the list (e.g. after creating a topic) without losing selection. */
  async refresh() {
    this.list = await api.listTopics();
  }
}

export const topics = new TopicStore();
