// Lightweight, module-level toast store. Survives client-side navigation (e.g. goto after
// curriculum generation), so a toast fired before navigating shows on the destination page.

type Tone = 'success' | 'error';
export type Toast = { id: number; msg: string; tone: Tone };

class ToastStore {
  items = $state<Toast[]>([]);
  private seq = 0;

  show(msg: string, tone: Tone = 'success', ttl = 4500) {
    const id = ++this.seq;
    this.items.push({ id, msg, tone });
    setTimeout(() => this.dismiss(id), ttl);
  }

  dismiss(id: number) {
    const i = this.items.findIndex((t) => t.id === id);
    if (i >= 0) this.items.splice(i, 1);
  }
}

export const toasts = new ToastStore();
