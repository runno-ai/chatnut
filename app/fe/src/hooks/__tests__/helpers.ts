/**
 * Shared MockEventSource for SSE hook tests.
 * Supports onopen, onmessage, onerror, addEventListener, and test helpers.
 */
export class MockEventSource {
  url: string;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  readyState = 0;
  private listeners: Record<string, EventListener[]> = {};

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, listener: EventListener) {
    (this.listeners[type] ??= []).push(listener);
  }

  removeEventListener(type: string, listener: EventListener) {
    this.listeners[type] = (this.listeners[type] ?? []).filter(
      (l) => l !== listener
    );
  }

  close() {
    this.readyState = 2;
  }

  // --- Test helpers ---

  /** Simulate a message event (triggers onmessage) */
  _emit(data: string) {
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  /** Simulate a named event (triggers addEventListener listeners) */
  _emitNamed(type: string) {
    for (const listener of this.listeners[type] ?? []) {
      listener(new Event(type));
    }
  }

  /** Simulate connection open */
  _triggerOpen() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  /** Simulate connection error */
  _triggerError() {
    this.onerror?.(new Event("error"));
  }
}
