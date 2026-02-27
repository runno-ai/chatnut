import { useMemo } from "react";
import type { ChatMessage } from "../types";
import { getRoleColor } from "../utils/roleColors";
import { MarkdownRenderer, extractMentions } from "./MarkdownRenderer";
import { MentionChip } from "./MentionChip";

interface MessageProps {
  message: ChatMessage;
}

function formatTimestamp(ts: string): string {
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMs / 3600000);

    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;

    return date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

export function Message({ message }: MessageProps) {
  const color = getRoleColor(message.sender);
  const mentions = useMemo(() => extractMentions(message.content), [message.content]);

  return (
    <div
      className="rounded-lg bg-gray-900 px-4 py-3 my-2"
      style={{ borderLeft: `3px solid ${color}` }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
        <span className="text-sm font-semibold" style={{ color }}>
          {message.sender}
        </span>
        <span className="text-xs text-gray-600">
          {formatTimestamp(message.created_at)}
        </span>
        {mentions.length > 0 && (
          <>
            <span className="text-xs text-gray-700">mentions</span>
            {mentions.map((m) => (
              <MentionChip key={m} name={m} />
            ))}
          </>
        )}
      </div>

      {/* Body */}
      <div className="text-base text-gray-300 prose prose-invert prose-base max-w-none [&_pre]:bg-gray-950 [&_pre]:rounded [&_pre]:p-2 [&_pre]:my-1 [&_code]:text-emerald-400 [&_code]:text-sm [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0 [&_h1]:text-lg [&_h2]:text-base [&_h3]:text-base [&_table]:text-sm [&_th]:px-2 [&_td]:px-2">
        <MarkdownRenderer content={message.content} />
      </div>
    </div>
  );
}
