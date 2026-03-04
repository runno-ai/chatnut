import { useEffect, useRef, useState, useCallback } from "react";
import { Message } from "./Message";
import { ConnectionStatus } from "./ConnectionStatus";
import { StatusBar } from "./StatusBar";
import { useSSE } from "../hooks/useSSE";
import { useStatus } from "../hooks/useStatus";
import type { ChatMessage } from "../types";

interface ChatViewProps {
  room: string | null;
  roomName: string | null;
  roomBranch?: string | null;
  roomProject?: string | null;
  isLive: boolean;
  reader?: string;
  onSelectProject?: (project: string) => void;
  onSelectBranch?: (branch: string) => void;
}

export function ChatView({ room, roomName, roomBranch, roomProject, isLive, reader, onSelectProject, onSelectBranch }: ChatViewProps) {
  const { messages: liveMessages, connectionStatus } = useSSE(
    isLive ? room : null
  );
  const statuses = useStatus(isLive ? room : null);
  const [staticMessages, setStaticMessages] = useState<ChatMessage[]>([]);
  const [loadingStatic, setLoadingStatic] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const lastMessageRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [newCount, setNewCount] = useState(0);
  const prevMessageCount = useRef(0);
  const scrollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const messages = isLive ? liveMessages : staticMessages;

  // Fetch static messages for archived (non-live) rooms
  useEffect(() => {
    if (isLive || !room) {
      setStaticMessages([]);
      return;
    }
    const controller = new AbortController();
    setLoadingStatic(true);
    fetch(`/api/chatrooms/${encodeURIComponent(room)}/messages`, {
      signal: controller.signal,
    })
      .then((res) => {
        if (!res.ok) throw new Error("Not found");
        return res.json();
      })
      .then((data) => {
        if (!controller.signal.aborted) {
          setStaticMessages(data.messages ?? []);
          requestAnimationFrame(() => {
            lastMessageRef.current?.scrollIntoView({ block: "start" });
          });
        }
      })
      .catch((err) => {
        if (err.name !== "AbortError") setStaticMessages([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingStatic(false);
        }
      });
    return () => controller.abort();
  }, [room, isLive]);

  // Track scroll position
  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setIsAtBottom(atBottom);
    if (atBottom) setNewCount(0);
  }, []);

  // Auto-scroll when new messages arrive (if at bottom)
  useEffect(() => {
    if (messages.length > prevMessageCount.current) {
      const added = messages.length - prevMessageCount.current;
      if (isAtBottom) {
        lastMessageRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else {
        setNewCount((c) => c + added);
      }
    }
    prevMessageCount.current = messages.length;
  }, [messages.length, isAtBottom]);

  // Scroll to last message on room change
  useEffect(() => {
    prevMessageCount.current = 0;
    setNewCount(0);
    setIsAtBottom(true);
    scrollTimeoutRef.current = setTimeout(() => {
      lastMessageRef.current?.scrollIntoView({ block: "start" });
    }, 50);
    return () => {
      if (scrollTimeoutRef.current) clearTimeout(scrollTimeoutRef.current);
    };
  }, [room]);

  // Auto mark-read when viewing messages at the bottom
  useEffect(() => {
    if (!room || !reader || messages.length === 0 || !isAtBottom) return;
    const lastMsg = messages[messages.length - 1];
    fetch(`/api/chatrooms/${encodeURIComponent(room)}/read`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reader, last_read_message_id: lastMsg.id }),
    }).catch(() => {}); // fire-and-forget
  }, [room, reader, messages.length, isAtBottom]);

  const scrollToBottom = () => {
    lastMessageRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    setNewCount(0);
  };

  if (!room) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-600">
        Select a chatroom
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col min-w-0 relative">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800 bg-gray-900/50">
        <div className="flex items-center gap-1.5 min-w-0">
          {/* Chat icon */}
          <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" className="text-gray-500 shrink-0">
            <path d="M2.678 11.894a1 1 0 0 1 .287.801 11 11 0 0 1-.398 2c1.395-.323 2.247-.697 2.634-.893a1 1 0 0 1 .71-.074A8 8 0 0 0 8 14c3.996 0 7-2.807 7-6s-3.004-6-7-6-7 2.808-7 6c0 1.468.617 2.83 1.678 3.894z"/>
          </svg>
          <h2 className="text-sm font-semibold text-gray-200 truncate">{roomName}</h2>
          {roomBranch && (
            <>
              <span className="text-gray-700 text-xs shrink-0">›</span>
              <button
                onClick={() => onSelectBranch?.(roomBranch)}
                className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors truncate min-w-0"
                title={`Filter by branch: ${roomBranch}`}
              >
                <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" className="shrink-0">
                  <path d="M9.5 3.25a2.25 2.25 0 113 2.122V6A2.5 2.5 0 0110 8.5H6A2.5 2.5 0 003.5 11v.128a2.251 2.251 0 11-1.5 0V5.372a2.25 2.25 0 111.5 0v1.836A3.99 3.99 0 016 6h4V5.372A2.25 2.25 0 019.5 3.25zm-6 0a.75.75 0 101.5 0 .75.75 0 00-1.5 0zm8.25-.75a.75.75 0 100 1.5.75.75 0 000-1.5zM2.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z"/>
                </svg>
                <span className="truncate">{roomBranch}</span>
              </button>
            </>
          )}
          {roomProject && (
            <>
              <span className="text-gray-700 text-xs shrink-0">›</span>
              <button
                onClick={() => onSelectProject?.(roomProject)}
                className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-300 transition-colors truncate min-w-0"
                title={`Filter by project: ${roomProject}`}
              >
                <svg width="11" height="11" viewBox="0 0 16 16" fill="currentColor" className="shrink-0">
                  <path d="M1.75 1A1.75 1.75 0 000 2.75v10.5C0 14.216.784 15 1.75 15h12.5A1.75 1.75 0 0016 13.25v-8.5A1.75 1.75 0 0014.25 3H7.5a.25.25 0 01-.2-.1l-.9-1.2C6.07 1.26 5.55 1 5 1H1.75z"/>
                </svg>
                <span className="truncate">{roomProject}</span>
              </button>
            </>
          )}
        </div>
        {isLive && <ConnectionStatus status={connectionStatus} />}
        {!isLive && (
          <span className="text-xs text-gray-600 bg-gray-800 px-2 py-0.5 rounded">
            Archived
          </span>
        )}
        <span className="text-xs text-gray-600 ml-auto">
          {messages.length} messages
        </span>
      </div>

      {/* Status bar — agent statuses for live rooms */}
      <StatusBar statuses={statuses} />

      {/* Messages */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-1"
      >
        {loadingStatic && (
          <div className="text-gray-500 text-sm py-4">Loading messages...</div>
        )}
        {!loadingStatic && messages.length === 0 && (
          <div className="text-gray-600 text-sm py-4">No messages yet.</div>
        )}
        {messages.map((msg, i) => (
          <div key={msg.id} ref={i === messages.length - 1 ? lastMessageRef : undefined}>
            <Message message={msg} isLast={i === messages.length - 1} />
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* New messages pill (live rooms only) */}
      {isLive && newCount > 0 && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10">
          <button
            onClick={scrollToBottom}
            className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium px-3 py-1.5 rounded-full shadow-lg transition-colors"
          >
            {newCount} new message{newCount > 1 ? "s" : ""}
          </button>
        </div>
      )}
    </div>
  );
}
