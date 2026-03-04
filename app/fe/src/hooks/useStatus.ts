// src/hooks/useStatus.ts
import { useState, useEffect, useRef } from "react";
import type { RoomStatus, TeamStatusResponse } from "../types";

export function useStatus(roomId: string | null): RoomStatus[] {
  const [statuses, setStatuses] = useState<RoomStatus[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    closedRef.current = false;

    if (!roomId) {
      setStatuses([]);
      return;
    }

    setStatuses([]);

    function connect() {
      if (closedRef.current) return;

      const es = new EventSource(
        `/api/stream/status?room_id=${encodeURIComponent(roomId!)}`
      );
      esRef.current = es;

      es.onmessage = (event) => {
        if (closedRef.current) return;
        try {
          const data = JSON.parse(event.data) as TeamStatusResponse;
          setStatuses(data.statuses ?? []);
        } catch {
          console.warn("useStatus: failed to parse status JSON");
        }
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;
        if (!closedRef.current) {
          retryRef.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      closedRef.current = true;
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
