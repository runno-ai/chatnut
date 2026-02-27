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

  /** Simulate a message event (triggers onmessage + addEventListener listeners) */
  _emit(data: string) {
    const event = new MessageEvent("message", { data });
    this.onmessage?.(event);
    for (const listener of this.listeners["message"] ?? []) {
      listener(event);
    }
  }

  /** Simulate a named event (triggers addEventListener listeners) */
  _emitNamed(type: string) {
    for (const listener of this.listeners[type] ?? []) {
      listener(new Event(type));
    }
  }

  /** Simulate connection open (triggers onopen + addEventListener listeners) */
  _triggerOpen() {
    this.readyState = 1;
    const event = new Event("open");
    this.onopen?.(event);
    for (const listener of this.listeners["open"] ?? []) {
      listener(event);
    }
  }

  /** Simulate connection error (sets readyState=CLOSED, triggers onerror + addEventListener listeners) */
  _triggerError() {
    this.readyState = 2;
    const event = new Event("error");
    this.onerror?.(event);
    for (const listener of this.listeners["error"] ?? []) {
      listener(event);
    }
  }
}
