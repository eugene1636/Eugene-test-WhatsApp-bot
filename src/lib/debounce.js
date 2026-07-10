/**
 * Inbound debounce (spec, Sprint 0): "on inbound, wait 20s; if more messages
 * arrive, batch and answer the whole thought once." A burst of 3 texts gets
 * 1 coherent reply.
 *
 * In-memory per-thread batcher. Each new message resets the timer; when the
 * window elapses with no new message, the handler runs once with the whole
 * batch.
 */
export class MessageDebouncer {
  /**
   * @param {number} windowMs - quiet period before flushing
   * @param {(key: string, batch: any[]) => Promise<void>|void} onFlush
   */
  constructor(windowMs, onFlush) {
    this.windowMs = windowMs;
    this.onFlush = onFlush;
    this.pending = new Map(); // key -> { batch: [], timer }
  }

  push(key, item) {
    let entry = this.pending.get(key);
    if (!entry) {
      entry = { batch: [], timer: null };
      this.pending.set(key, entry);
    }
    entry.batch.push(item);
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = setTimeout(() => this.flush(key), this.windowMs);
  }

  /** Drop anything pending for a thread (e.g. a human took over mid-burst). */
  cancel(key) {
    const entry = this.pending.get(key);
    if (!entry) return;
    if (entry.timer) clearTimeout(entry.timer);
    this.pending.delete(key);
  }

  async flush(key) {
    const entry = this.pending.get(key);
    if (!entry) return;
    this.pending.delete(key);
    if (entry.timer) clearTimeout(entry.timer);
    try {
      await this.onFlush(key, entry.batch);
    } catch (err) {
      console.error(`[debounce] flush failed for ${key}:`, err);
    }
  }
}
