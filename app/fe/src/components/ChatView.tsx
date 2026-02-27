import { useEffect, useRef, useState, useCallback } from "react";
import { Message } from "./Message";
import { ConnectionStatus } from "./ConnectionStatus";
import { useSSE } from "../hooks/useSSE";
import type { ChatMessage } from "../types";

interface ChatViewProps {
  room: string | null;
  roomName: string | null;
  isLive: boolean;
}

export function ChatView({ room, roomName, isLive }: ChatViewProps) {
  const { messages: liveMessages, connectionStatus } = useSSE(
    isLive ? room : null
  );
  const [staticMessages, setStaticMessages] = useState<ChatMessage[]>([]);
  const [loadingStatic, setLoadingStatic] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [newCount, setNewCount] = useState(0);
  const prevMessageCount = useRef(0);

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
        setStaticMessages(data.messages || []);
      })
      .catch((err) => {
        if (err.name !== "AbortError") setStaticMessages([]);
      })
      .finally(() => setLoadingStatic(false));
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
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
      } else {
        setNewCount((c) => c + added);
      }
    }
    prevMessageCount.current = messages.length;
  }, [messages.length, isAtBottom]);

  // Scroll to top on room change (read from beginning)
  useEffect(() => {
    prevMessageCount.current = 0;
    setNewCount(0);
    setIsAtBottom(false);
    setTimeout(() => {
      containerRef.current?.scrollTo(0, 0);
    }, 50);
  }, [room]);

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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
    <div className="flex-1 flex flex-col min-w-0">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800 bg-gray-900/50">
        <h2 className="text-sm font-semibold text-gray-200">{roomName}</h2>
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
        {messages.map((msg) => (
          <Message key={msg.id} message={msg} />
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
