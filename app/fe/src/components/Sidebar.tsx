import { useState } from "react";
import type { ChatroomInfo, SearchResult } from "../types";
import { getRoleColor } from "../utils/roleColors";

interface SidebarProps {
  active: ChatroomInfo[];
  archived: ChatroomInfo[];
  branches: string[];
  loading: boolean;
  selectedRoom: string | null;
  collapsed: boolean;
  width: number;
  projects: string[];
  selectedProject: string | null;
  selectedBranch: string | null;
  searchQuery: string;
  searchResult: SearchResult | null;
  searchLoading: boolean;
  onSelectRoom: (roomId: string) => void;
  onToggleCollapse: () => void;
  onSelectProject: (project: string | null) => void;
  onSelectBranch: (branch: string | null) => void;
  onSearchChange: (query: string) => void;
}

function formatRelativeTime(ts?: string): string {
  if (!ts) return "";
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin}m`;
    if (diffHr < 24) return `${diffHr}h`;
    if (diffDays < 7) return `${diffDays}d`;
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

export function Sidebar({
  active,
  archived,
  branches,
  loading,
  selectedRoom,
  collapsed,
  width,
  projects,
  selectedProject,
  selectedBranch,
  searchQuery,
  searchResult,
  searchLoading,
  onSelectRoom,
  onToggleCollapse,
  onSelectProject,
  onSelectBranch,
  onSearchChange,
}: SidebarProps) {
  if (collapsed) {
    return (
      <div className="w-10 bg-gray-900 border-r border-gray-800 flex flex-col items-center pt-3">
        <button
          onClick={onToggleCollapse}
          className="text-gray-400 hover:text-gray-200 p-1"
          title="Expand sidebar"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M6 3l5 5-5 5V3z" />
          </svg>
        </button>
      </div>
    );
  }

  // Sort active: by last message time (newest first)
  const sortedActive = [...active].sort((a, b) => {
    return (b.lastMessageTs ?? "").localeCompare(a.lastMessageTs ?? "");
  });

  // Search result highlighting
  const searchRoomIds = new Set(searchResult?.rooms?.map((r) => r.id) ?? []);
  const messageMatchRoomIds = new Map(
    searchResult?.message_rooms?.map((mr) => [mr.room_id, mr.match_count]) ?? []
  );

  const isSearching = searchQuery.length >= 2;

  // Filter rooms by search if active
  const filteredActive = isSearching
    ? sortedActive.filter((r) => searchRoomIds.has(r.id) || messageMatchRoomIds.has(r.id))
    : sortedActive;

  return (
    <div className="bg-gray-900 border-r border-gray-800 flex flex-col shrink-0" style={{ width }}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-gray-800">
        <span className="text-sm font-semibold text-gray-300">Chatrooms</span>
        <button
          onClick={onToggleCollapse}
          className="text-gray-400 hover:text-gray-200 p-1"
          title="Collapse sidebar"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M10 3l-5 5 5 5V3z" />
          </svg>
        </button>
      </div>

      {/* Filters */}
      <div className="px-3 py-2 space-y-2 border-b border-gray-800">
        <div className="flex gap-2">
          <select
            value={selectedProject ?? ""}
            onChange={(e) => {
              onSelectProject(e.target.value || null);
              onSelectBranch(null);
            }}
            className="flex-1 bg-gray-800 text-gray-300 text-xs rounded px-2 py-1.5 border border-gray-700 focus:border-blue-500 focus:outline-none"
          >
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <select
            value={selectedBranch ?? ""}
            onChange={(e) => onSelectBranch(e.target.value || null)}
            disabled={!selectedProject}
            className="flex-1 bg-gray-800 text-gray-300 text-xs rounded px-2 py-1.5 border border-gray-700 focus:border-blue-500 focus:outline-none disabled:opacity-40"
          >
            <option value="">All branches</option>
            {branches.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </div>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Search rooms & messages..."
          className="w-full bg-gray-800 text-gray-300 text-xs rounded px-2 py-1.5 border border-gray-700 focus:border-blue-500 focus:outline-none placeholder-gray-600"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="px-3 py-4 text-sm text-gray-500">Loading...</div>
        )}

        {isSearching && searchLoading && (
          <div className="px-3 py-4 text-sm text-gray-500">Searching...</div>
        )}

        {isSearching && !searchLoading && filteredActive.length === 0 && (
          <div className="px-3 py-4 text-sm text-gray-500">No results found.</div>
        )}

        {/* Live */}
        {filteredActive.length > 0 && (
          <div className="px-2 pt-3">
            <div className="px-2 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Live
            </div>
            {filteredActive.map((room) => (
              <RoomItem
                key={room.id}
                room={room}
                isLive
                isSelected={selectedRoom === room.id}
                matchCount={messageMatchRoomIds.get(room.id)}
                showProject={!selectedProject}
                onClick={() => onSelectRoom(room.id)}
              />
            ))}
          </div>
        )}

        {/* Archived */}
        {!isSearching && archived.length > 0 && (
          <ArchivedSection
            archived={archived}
            selectedRoom={selectedRoom}
            showProject={!selectedProject}
            onSelectRoom={onSelectRoom}
          />
        )}
      </div>
    </div>
  );
}

const ARCHIVE_PAGE_SIZE = 10;

function ArchivedSection({
  archived,
  selectedRoom,
  showProject,
  onSelectRoom,
}: {
  archived: ChatroomInfo[];
  selectedRoom: string | null;
  showProject: boolean;
  onSelectRoom: (roomId: string) => void;
}) {
  const [showCount, setShowCount] = useState(ARCHIVE_PAGE_SIZE);
  const visible = archived.slice(0, showCount);
  const remaining = archived.length - showCount;

  return (
    <div className="px-2 pt-3">
      <div className="px-2 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wider">
        Archived
      </div>
      {visible.map((room) => (
        <RoomItem
          key={room.id}
          room={room}
          isSelected={selectedRoom === room.id}
          showProject={showProject}
          onClick={() => onSelectRoom(room.id)}
        />
      ))}
      {remaining > 0 && (
        <button
          onClick={() => setShowCount((c) => c + ARCHIVE_PAGE_SIZE)}
          className="w-full text-center text-xs text-gray-500 hover:text-gray-300 py-2 transition-colors"
        >
          Show more ({remaining})
        </button>
      )}
    </div>
  );
}

function RoomItem({
  room,
  isLive,
  isSelected,
  matchCount,
  showProject,
  onClick,
}: {
  room: ChatroomInfo;
  isLive?: boolean;
  isSelected: boolean;
  matchCount?: number;
  showProject?: boolean;
  onClick: () => void;
}) {
  const timeStr = formatRelativeTime(room.lastMessageTs);

  const roles = room.roleCounts
    ? Object.entries(room.roleCounts).sort(([, a], [, b]) => b - a)
    : [];

  return (
    <button
      onClick={onClick}
      className={`relative w-full text-left px-2 py-2 rounded-md mb-0.5 transition-colors ${
        isSelected
          ? "bg-gray-800 text-gray-100"
          : "text-gray-400 hover:bg-gray-800/50 hover:text-gray-200"
      }`}
    >
      {isSelected && (
        <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full bg-blue-500" />
      )}
      <div className="flex items-center gap-2">
        {isLive && (
          <span className="relative flex h-2 w-2 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
          </span>
        )}
        <span className="text-sm font-medium truncate">{room.name}</span>
        {matchCount != null && matchCount > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-yellow-500/20 text-yellow-400">
            {matchCount} match{matchCount > 1 ? "es" : ""}
          </span>
        )}
        <span className="text-xs text-gray-600 ml-auto shrink-0">
          {timeStr}
        </span>
      </div>
      {(showProject || room.branch) && (
        <div className="flex gap-1 mt-0.5 pl-4">
          {showProject && (
            <span className="text-[10px] text-gray-600">{room.project}</span>
          )}
          {room.branch && (
            <span className="text-[10px] text-gray-600">/{room.branch}</span>
          )}
        </div>
      )}
      {roles.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1 pl-4">
          <span className="inline-flex items-center text-[10px] leading-tight px-1.5 py-0.5 rounded-full bg-gray-700/50 text-gray-400">
            {room.messageCount}
          </span>
          {roles.map(([role, count]) => (
            <span
              key={role}
              className="inline-flex items-center gap-0.5 text-[10px] leading-tight px-1.5 py-0.5 rounded-full"
              style={{
                backgroundColor: getRoleColor(role) + "12",
                color: getRoleColor(role) + "90",
              }}
            >
              {role}
              <span className="opacity-60">{count}</span>
            </span>
          ))}
        </div>
      )}
    </button>
  );
}
