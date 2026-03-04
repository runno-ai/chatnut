// src/hooks/useStatus.ts
import { useState, useEffect, useRef } from "react";
import type { RoomStatus } from "../types";

export function useStatus(roomId: string | null): RoomStatus[] {
  const [statuses, setStatuses] = useState<RoomStatus[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let closed = false;

    if (!roomId) {
      setStatuses([]);
      return;
    }

    setStatuses([]);

    function connect() {
      if (closed) return;

      const es = new EventSource(
        `/api/stream/status?room_id=${encodeURIComponent(roomId!)}`
      );
      esRef.current = es;

      es.onmessage = (event) => {
        if (closed) return;
        try {
          const data = JSON.parse(event.data);
          if (data && Array.isArray(data.statuses)) {
            setStatuses(data.statuses);
          }
        } catch {
          console.warn("useStatus: failed to parse status JSON");
        }
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;
        if (!closed) {
          retryRef.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      closed = true;
      esRef.current?.close();
      esRef.current = null;
      if (retryRef.current) {
        clearTimeout(retryRef.current);
        retryRef.current = null;
      }
      setStatuses([]);
    };
  }, [roomId]);

  return statuses;
}
