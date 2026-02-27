// src/hooks/useChatrooms.ts
import { useState, useEffect, useRef } from "react";
import type { ChatroomInfo, ChatroomsResponse } from "../types";

export function useChatrooms(project?: string) {
  const [active, setActive] = useState<ChatroomInfo[]>([]);
  const [archived, setArchived] = useState<ChatroomInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let es: EventSource | null = null;
    let closed = false;

    setLoading(true);
    setActive([]);
    setArchived([]);

    function connect() {
      if (closed) return;
      const params = new URLSearchParams();
      if (project) params.set("project", project);
      const qs = params.toString();
      es = new EventSource(`/api/stream/chatrooms${qs ? `?${qs}` : ""}`);

      es.onmessage = (e) => {
        try {
          const data: ChatroomsResponse = JSON.parse(e.data);
          setActive(data.active);
          setArchived(data.archived);
          setLoading(false);
        } catch {}
      };

      es.onerror = () => {
        es?.close();
        if (!closed) {
          retryRef.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      closed = true;
      es?.close();
      if (retryRef.current) clearTimeout(retryRef.current);
    };
  }, [project]);

  return { active, archived, loading };
}
