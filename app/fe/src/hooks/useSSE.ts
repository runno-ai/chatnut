// src/hooks/useSSE.ts
import { useState, useEffect, useRef } from "react";
import type { ChatMessage } from "../types";

type ConnectionStatus = "connecting" | "connected" | "disconnected";

export function useSSE(roomId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Batch incoming messages with requestAnimationFrame
  const pendingRef = useRef<ChatMessage[]>([]);
  const rafIdRef = useRef<number | null>(null);

  useEffect(() => {
    // Reset batch state from any previous room/connection
    pendingRef.current = [];
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }

    if (!roomId) {
      setMessages([]);
      setConnectionStatus("disconnected");
      return;
    }

    let closed = false;
    setMessages([]);
    setConnectionStatus("connecting");

    function flushPending() {
      rafIdRef.current = null;
      if (closed) return;
      const batch = pendingRef.current;
      pendingRef.current = [];
      if (batch.length > 0) {
        setMessages((prev) => [...prev, ...batch]);
      }
    }

    function connect() {
      if (closed) return;

      const es = new EventSource(
        `/api/stream/messages?room_id=${encodeURIComponent(roomId!)}`
      );
      esRef.current = es;

      es.onopen = () => {
        if (!closed) setConnectionStatus("connected");
      };

      es.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as ChatMessage;
          pendingRef.current.push(msg);
          if (rafIdRef.current === null) {
            rafIdRef.current = requestAnimationFrame(flushPending);
          }
        } catch {
          console.warn("useSSE: failed to parse message JSON");
        }
      };

      es.addEventListener("reset", () => {
        if (!closed) setMessages([]);
      });

      es.onerror = () => {
        es.close();
        esRef.current = null;
        if (closed) {
          setConnectionStatus("disconnected");
        } else {
          setConnectionStatus("connecting");
          retryRef.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      closed = true;
      esRef.current?.close();
      esRef.current = null;
      if (retryRef.current) clearTimeout(retryRef.current);
      retryRef.current = null;
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      pendingRef.current = [];
      setConnectionStatus("disconnected");
    };
  }, [roomId]);

  return { messages, connectionStatus };
}
