/**
 * BroadcastChannel-based sync between phone UI and /projector route
 * (Single device, single browser context).
 *
 * NOTE: We persist the latest state to localStorage *intentionally* so the
 * /projector window can pick up the current state when opened later.
 * This is non-sensitive UI state only (book/chapter/verse, status flags,
 * detection coords) — no PII, tokens, or credentials.
 */

const CHANNEL = "torah-aid-projector";

class ProjectorBus {
  constructor() {
    try {
      this.bc = new BroadcastChannel(CHANNEL);
    } catch (e) {
      console.warn("[projectorBus] BroadcastChannel unavailable:", e);
      this.bc = null;
    }
    this.listeners = new Set();
    if (this.bc) {
      this.bc.onmessage = (ev) => {
        for (const fn of this.listeners) fn(ev.data);
      };
    }
    this.STORAGE_KEY = "torah-aid-projector-state";
  }
  send(msg) {
    if (this.bc) this.bc.postMessage(msg);
    if (msg && msg.type === "state") {
      try {
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(msg.payload));
      } catch (e) {
        console.warn("[projectorBus] localStorage write failed:", e);
      }
    }
  }
  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
  getCachedState() {
    try {
      const v = localStorage.getItem(this.STORAGE_KEY);
      return v ? JSON.parse(v) : null;
    } catch (e) {
      console.warn("[projectorBus] localStorage read failed:", e);
      return null;
    }
  }
}

export const projectorBus = new ProjectorBus();
