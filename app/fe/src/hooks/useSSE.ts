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
  const rafScheduledRef = useRef(false);

  useEffect(() => {
    if (!roomId) {
      setMessages([]);
      setConnectionStatus("disconnected");
      return;
    }

    let closed = false;
    setMessages([]);
    setConnectionStatus("connecting");

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
          if (!rafScheduledRef.current) {
            rafScheduledRef.current = true;
            requestAnimationFrame(() => {
              const batch = pendingRef.current;
              pendingRef.current = [];
              rafScheduledRef.current = false;
              setMessages((prev) => [...prev, ...batch]);
            });
          }
        } catch {
          console.warn("useSSE: failed to parse message JSON");
        }
      };

      es.addEventListener("reset", () => {
        setMessages([]);
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
      setConnectionStatus("disconnected");
    };
  }, [roomId]);

  return { messages, connectionStatus };
}
