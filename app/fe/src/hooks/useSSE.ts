// src/hooks/useSSE.ts
import { useState, useEffect, useRef } from "react";
import type { ChatMessage } from "../types";

type ConnectionStatus = "connecting" | "connected" | "disconnected";

export function useSSE(roomId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!roomId) {
      setMessages([]);
      setConnectionStatus("disconnected");
      return;
    }

    setMessages([]);
    setConnectionStatus("connecting");

    const es = new EventSource(
      `/api/stream/messages?room_id=${encodeURIComponent(roomId)}`
    );
    esRef.current = es;

    es.onopen = () => {
      setConnectionStatus("connected");
    };

    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as ChatMessage;
        setMessages((prev) => [...prev, msg]);
      } catch {}
    };

    es.addEventListener("reset", () => {
      setMessages([]);
    });

    es.onerror = () => {
      setConnectionStatus("disconnected");
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [roomId]);

  return { messages, connectionStatus };
}
