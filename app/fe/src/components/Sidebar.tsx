import { useState, useEffect } from "react";
import type { ChatroomInfo, SearchResult } from "../types";
import { getRoleColor } from "../utils/roleColors";
import { Select } from "./Select";

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
  onDeleteRoom: (roomId: string) => void;
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
  onDeleteRoom,
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

  // Sort by last message time (newest first)
  const sortedActive = [...active].sort((a, b) =>
    (b.lastMessageTs ?? "").localeCompare(a.lastMessageTs ?? "")
  );
  const sortedArchived = [...archived].sort((a, b) =>
    (b.lastMessageTs ?? "").localeCompare(a.lastMessageTs ?? "")
  );

  // Search result highlighting
  const searchRoomIds = new Set(searchResult?.rooms?.map((r) => r.id) ?? []);
  const messageMatchRoomIds = new Map(
    searchResult?.message_rooms?.map((mr) => [mr.room_id, mr.match_count]) ?? []
  );

  const isSearching = searchQuery.length >= 2;

  // Filter rooms by search
  const matchesSearch = (r: ChatroomInfo) =>
    searchRoomIds.has(r.id) || messageMatchRoomIds.has(r.id) || r.name.toLowerCase().includes(searchQuery.toLowerCase());
  const filteredActive = isSearching
    ? sortedActive.filter(matchesSearch)
    : sortedActive;
  const filteredArchived = isSearching
    ? sortedArchived.filter(matchesSearch)
    : sortedArchived;

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
      <div className="px-3 py-2 space-y-1.5 border-b border-gray-800">
        <Select
          value={selectedProject ?? ""}
          onChange={(v) => { onSelectProject(v || null); onSelectBranch(null); }}
          options={projects.map((p) => ({ value: p, label: p }))}
          placeholder="All projects"
          icon={<svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><path d="M1.75 1A1.75 1.75 0 000 2.75v10.5C0 14.216.784 15 1.75 15h12.5A1.75 1.75 0 0016 13.25v-8.5A1.75 1.75 0 0014.25 3H7.5a.25.25 0 01-.2-.1l-.9-1.2C6.07 1.26 5.55 1 5 1H1.75z" /></svg>}
        />
        <Select
          value={selectedBranch ?? ""}
          onChange={(v) => onSelectBranch(v || null)}
          options={branches.map((b) => ({ value: b, label: b }))}
          placeholder="All branches"
          disabled={!selectedProject}
          icon={<svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor"><path d="M9.5 3.25a2.25 2.25 0 113 2.122V6A2.5 2.5 0 0110 8.5H6A2.5 2.5 0 003.5 11v.128a2.251 2.251 0 11-1.5 0V5.372a2.25 2.25 0 111.5 0v1.836A3.99 3.99 0 016 6h4V5.372A2.25 2.25 0 019.5 3.25zm-6 0a.75.75 0 10-1.5 0 .75.75 0 001.5 0zm8.25-.75a.75.75 0 100 1.5.75.75 0 000-1.5zM2.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z" /></svg>}
        />
        <div className="relative">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-500 pointer-events-none">
            <path d="M11.5 7a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0zm-.82 4.74a6 6 0 111.06-1.06l3.04 3.04a.75.75 0 11-1.06 1.06l-3.04-3.04z" />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search rooms & messages..."
            className="w-full bg-gray-800/50 text-gray-300 text-xs rounded-full pl-7 pr-2 py-1.5 border-none focus:ring-1 focus:ring-blue-500/50 focus:outline-none placeholder-gray-600"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="px-3 py-4 text-sm text-gray-500">Loading...</div>
        )}

        {isSearching && searchLoading && (
          <div className="px-3 py-4 text-sm text-gray-500">Searching...</div>
        )}

        {isSearching && !searchLoading && filteredActive.length === 0 && filteredArchived.length === 0 && (
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
        {filteredArchived.length > 0 && (
          <ArchivedSection
            archived={filteredArchived}
            selectedRoom={selectedRoom}
            showProject={!selectedProject}
            onSelectRoom={onSelectRoom}
            onDeleteRoom={onDeleteRoom}
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
  onDeleteRoom,
}: {
  archived: ChatroomInfo[];
  selectedRoom: string | null;
  showProject: boolean;
  onSelectRoom: (roomId: string) => void;
  onDeleteRoom: (roomId: string) => void;
}) {
  const [showCount, setShowCount] = useState(ARCHIVE_PAGE_SIZE);
  const [confirmDelete, setConfirmDelete] = useState<ChatroomInfo | null>(null);
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
          onDelete={() => setConfirmDelete(room)}
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
      {confirmDelete && (
        <DeleteConfirmDialog
          room={confirmDelete}
          onConfirm={() => { onDeleteRoom(confirmDelete.id); setConfirmDelete(null); }}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </div>
  );
}

function DeleteConfirmDialog({
  room,
  onConfirm,
  onCancel,
}: {
  room: ChatroomInfo;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onCancel}>
      <div role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title" aria-describedby="delete-dialog-desc" className="bg-gray-800 border border-gray-700 rounded-lg shadow-xl p-4 max-w-sm mx-4" onClick={(e) => e.stopPropagation()}>
        <div id="delete-dialog-title" className="text-sm font-medium text-gray-200 mb-2">Delete chatroom?</div>
        <p id="delete-dialog-desc" className="text-xs text-gray-400 mb-4">
          Permanently delete <span className="text-gray-200 font-medium">{room.name}</span> and all its messages.
          This cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 text-xs rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-3 py-1.5 text-xs rounded bg-red-600 text-white hover:bg-red-500 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
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
  onDelete,
}: {
  room: ChatroomInfo;
  isLive?: boolean;
  isSelected: boolean;
  matchCount?: number;
  showProject?: boolean;
  onClick: () => void;
  onDelete?: () => void;
}) {
  const timeStr = formatRelativeTime(room.lastMessageTs);

  const roles = room.roleCounts
    ? Object.entries(room.roleCounts).sort(([, a], [, b]) => b - a)
    : [];

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } }}
      className={`group relative w-full text-left px-2 py-2 rounded-md mb-0.5 transition-colors cursor-pointer ${
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
        {onDelete && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            aria-label={`Delete room ${room.name}`}
            className="shrink-0 p-0.5 rounded text-gray-600 hover:text-red-400 hover:bg-red-400/10 transition-colors opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100"
            title="Delete room"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path d="M11 1.75V3h2.25a.75.75 0 010 1.5H2.75a.75.75 0 010-1.5H5V1.75C5 .784 5.784 0 6.75 0h2.5C10.216 0 11 .784 11 1.75zM6.5 1.75v1.25h3V1.75a.25.25 0 00-.25-.25h-2.5a.25.25 0 00-.25.25zM4.997 6.178a.75.75 0 10-1.493.144L4.2 13.34a1.75 1.75 0 001.742 1.66h4.117a1.75 1.75 0 001.741-1.66l.696-7.018a.75.75 0 10-1.493-.144L10.306 13.2a.25.25 0 01-.249.237H5.944a.25.25 0 01-.249-.237L4.997 6.178z" />
            </svg>
          </button>
        )}
        <span className="text-xs text-gray-600 shrink-0 ml-auto">
          {timeStr}
        </span>
      </div>
      {showProject && (
        <div className="mt-0.5 pl-4 text-[10px] text-gray-600 truncate">{room.project}</div>
      )}
      {room.branch && (
        <div className="mt-0.5 pl-4 text-[10px] text-gray-600 truncate">{room.branch}</div>
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
    </div>
  );
}
