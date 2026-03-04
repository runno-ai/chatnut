// src/components/StatusBar.tsx
import type { RoomStatus } from "../types";
import { timeAgo } from "../utils/timeAgo";

const STALE_MS = 5 * 60 * 1000; // 5 minutes

function isStale(updatedAt: string): boolean {
  try {
    return Date.now() - new Date(updatedAt).getTime() > STALE_MS;
  } catch {
    return false;
  }
}

function statusColor(status: string, updatedAt: string): string {
  if (/block/i.test(status)) return "text-yellow-500";
  if (isStale(updatedAt)) return "text-gray-500";
  return "text-green-400";
}

function dotColor(status: string, updatedAt: string): string {
  if (/block/i.test(status)) return "bg-yellow-500";
  if (isStale(updatedAt)) return "bg-gray-500";
  return "bg-green-400";
}

interface StatusBarProps {
  statuses: RoomStatus[];
}

export function StatusBar({ statuses }: StatusBarProps) {
  if (statuses.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2 border-b border-gray-800 bg-gray-900/30">
      {statuses.map((s) => (
        <div key={s.sender} className="flex items-center gap-1.5 min-w-0">
          <span
            className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor(s.status, s.updated_at)}`}
          />
          <span className="text-xs font-medium text-gray-400 shrink-0">
            {s.sender}
          </span>
          <span className={`text-xs truncate ${statusColor(s.status, s.updated_at)}`}>
            {s.status}
          </span>
          <span className="text-xs text-gray-600 shrink-0">
            {timeAgo(s.updated_at)}
          </span>
        </div>
      ))}
    </div>
  );
}
