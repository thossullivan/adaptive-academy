import { mkdirSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// There is only ever one demo topic in the shared e2e db, and specs in the desktop and phone
// projects run in parallel. A cross-process shared/exclusive lock keeps them from pulling the
// demo out from under each other:
// - withDemoLock (exclusive): for a spec that creates or removes the demo. It waits until no
//   shared holder is left.
// - withDemoShared (shared): for a spec that only needs the demo to exist while it reads pages.
//   Shared holders run side by side; each makes sure the demo exists while it briefly holds the
//   exclusive lock, so the demo is never created twice.
const BASE = join(tmpdir(), `aa-e2e-demo-${process.env.E2E_API_PORT ?? 18765}`);
const LOCK = `${BASE}.lock`;
const READERS = `${BASE}.readers`;
const STALE_MS = 180_000; // a holder this old belongs to a run that died mid-test

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function isStale(path: string): boolean {
  try {
    return Date.now() - statSync(path).mtimeMs > STALE_MS;
  } catch {
    return false; // released meanwhile
  }
}

async function acquire(deadline: number) {
  for (;;) {
    try {
      mkdirSync(LOCK);
      return;
    } catch {
      if (isStale(LOCK)) rmSync(LOCK, { recursive: true, force: true });
      if (Date.now() > deadline) throw new Error('timed out waiting for the demo lock');
      await sleep(250);
    }
  }
}

function release() {
  rmSync(LOCK, { recursive: true, force: true });
}

function liveReaders(): string[] {
  let names: string[] = [];
  try {
    names = readdirSync(READERS);
  } catch {
    return [];
  }
  return names.filter((n) => {
    const p = join(READERS, n);
    if (!isStale(p)) return true;
    rmSync(p, { force: true });
    return false;
  });
}

/** Run `fn` holding the demo exclusively (no other holder of either kind). */
export async function withDemoLock<T>(fn: () => Promise<T>, waitMs = 150_000): Promise<T> {
  const deadline = Date.now() + waitMs;
  await acquire(deadline);
  try {
    // New shared holders are blocked by the lock; wait for the current ones to finish.
    while (liveReaders().length) {
      if (Date.now() > deadline) throw new Error('timed out waiting for demo readers to finish');
      await sleep(250);
    }
    return await fn();
  } finally {
    release();
  }
}

/**
 * Run `fn` while the demo is guaranteed to stay put. `setup` runs first, under the exclusive
 * lock (use it to create the demo if it is missing); `fn` then runs alongside other shared
 * holders.
 */
export async function withDemoShared<S, T>(
  setup: () => Promise<S>,
  fn: (s: S) => Promise<T>,
  waitMs = 150_000
): Promise<T> {
  const deadline = Date.now() + waitMs;
  const me = join(READERS, `${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  await acquire(deadline);
  let s: S;
  try {
    s = await setup();
    mkdirSync(READERS, { recursive: true });
    writeFileSync(me, '');
  } finally {
    release();
  }
  try {
    return await fn(s);
  } finally {
    rmSync(me, { force: true });
  }
}
