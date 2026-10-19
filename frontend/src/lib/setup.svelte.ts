import { api } from './api';
import { llmBlocked } from './setup';
import type { SetupStatus } from './types';

/** Shared LLM-readiness state (GET /api/setup) for the setup notice and create forms. */
class SetupStore {
  status = $state<SetupStatus | null>(null);
  blocked = $derived(llmBlocked(this.status));

  /** Re-check on every page that needs it: a restarted API with a new key shows up
   *  without a full reload. A failed check keeps the last known status. */
  async refresh() {
    try {
      this.status = await api.getSetup();
    } catch (e) {
      console.error('Failed to load /api/setup', e);
    }
  }
}

export const setup = new SetupStore();
