import { browser } from '$app/environment';
import { api } from './api';
import { draftStore } from './notebook';
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

  /** Forget a topic that no longer exists (a deleted topic, the removed demo); select the next one. */
  forget(id: number) {
    this.list = this.list.filter((t) => t.id !== id);
    if (this.currentId === id) {
      this.currentId = this.list[0]?.id ?? null;
      if (browser) localStorage.removeItem(KEY);
    }
  }

  /** Delete a topic for good (`del`: the demo has its own route), then select the next one
   *  (or none) and re-fetch the list. Its concepts' note drafts go too: the database hands
   *  their ids to the next concepts made, and a kept draft would restore into one of them. */
  async remove(id: number, del: (id: number) => Promise<unknown> = api.deleteTopic) {
    const conceptIds = await this.conceptIds(id);
    await del(id);
    draftStore().forget(conceptIds);
    this.forget(id);
    await this.refresh();
  }

  /** Every concept id the topic has: the list's copy, and a fresh one in case concepts were
   *  made since the list loaded. Never throws. */
  private async conceptIds(id: number): Promise<Set<number>> {
    const ids = new Set((this.list.find((t) => t.id === id)?.concepts ?? []).map((c) => c.id));
    const fresh = await api.getTopic(id).catch(() => null);
    for (const c of fresh?.concepts ?? []) ids.add(c.id);
    return ids;
  }

  /** Build (or reuse) the demo topic and make it current. Returns its id. */
  async openDemo(): Promise<number> {
    const { topic_id } = await api.createDemo();
    // Select first: the list then arrives with the demo already current (one dashboard load).
    this.select(topic_id);
    await this.refresh();
    return topic_id;
  }

  /** Re-fetch the list (e.g. after creating a topic) without losing selection. */
  async refresh() {
    this.list = await api.listTopics();
  }
}

export const topics = new TopicStore();
