import "./index.css";
import { useState, useMemo, useCallback, useRef } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatView } from "./components/ChatView";
import { useChatrooms } from "./hooks/useChatrooms";
import { useProjects } from "./hooks/useProjects";
import { useSearch } from "./hooks/useSearch";

const READER_STORAGE_KEY = "tc:reader-id";
let volatileReaderId: string | null = null;

function getOrCreateReaderId(): string {
  try {
    const existing = localStorage.getItem(READER_STORAGE_KEY);
    if (existing) return existing;
    const created = crypto.randomUUID();
    localStorage.setItem(READER_STORAGE_KEY, created);
    return created;
  } catch {
    if (!volatileReaderId) volatileReaderId = crypto.randomUUID();
    return volatileReaderId;
  }
}

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 500;
const SIDEBAR_DEFAULT = 280;

const SS_PROJECT = "tc:project";
const SS_BRANCH = "tc:branch";
const SS_ROOM = "tc:room";

function ssGet(key: string): string | null {
  try { return sessionStorage.getItem(key); } catch { return null; }
}
function ssSet(key: string, v: string | null) {
  try { if (v) sessionStorage.setItem(key, v); else sessionStorage.removeItem(key); } catch {}
}

export default function App() {
  const readerId = useMemo(() => getOrCreateReaderId(), []);
  const [selectedProject, setSelectedProject] = useState<string | null>(ssGet(SS_PROJECT));
  const [selectedBranch, setSelectedBranch] = useState<string | null>(ssGet(SS_BRANCH));
  const [searchQuery, setSearchQuery] = useState("");

  const { active, archived, loading } = useChatrooms(
    selectedProject ?? undefined,
    readerId
  );
  const projects = useProjects();

  // Derive branches from unfiltered rooms (before branch filter)
  const branches = [...new Set([...active, ...archived].map((r) => r.branch).filter(Boolean))] as string[];

  // Client-side branch filtering
  const filteredActive = selectedBranch
    ? active.filter((r) => r.branch === selectedBranch)
    : active;
  const filteredArchived = selectedBranch
    ? archived.filter((r) => r.branch === selectedBranch)
    : archived;
  const { result: searchResult, loading: searchLoading } = useSearch(
    searchQuery,
    selectedProject ?? undefined
  );

  const [selectedRoom, setSelectedRoom] = useState<string | null>(ssGet(SS_ROOM));
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const dragging = useRef(false);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      setSidebarWidth(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, ev.clientX)));
    };
    const onUp = () => {
      dragging.current = false;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, []);

  // Active rooms are live-streamable via SSE, archived are static
  const activeIds = useMemo(
    () => new Set(active.map((r) => r.id)),
    [active]
  );
  const isLive = selectedRoom ? activeIds.has(selectedRoom) : false;

  const handleDeleteRoom = useCallback(async (roomId: string) => {
    try {
      const res = await fetch(`/api/chatrooms/${roomId}`, { method: "DELETE" });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        console.warn("Delete failed:", res.status, body?.detail ?? "");
        return;
      }
      if (selectedRoom === roomId) {
        setSelectedRoom(null);
        ssSet(SS_ROOM, null);
      }
    } catch (err) {
      console.warn("Delete failed:", err);
    }
  }, [selectedRoom]);

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      <Sidebar
        active={filteredActive}
        archived={filteredArchived}
        branches={branches}
        loading={loading}
        selectedRoom={selectedRoom}
        collapsed={sidebarCollapsed}
        width={sidebarWidth}
        projects={projects}
        selectedProject={selectedProject}
        selectedBranch={selectedBranch}
        searchQuery={searchQuery}
        searchResult={searchResult}
        searchLoading={searchLoading}
        onSelectRoom={(v) => { setSelectedRoom(v); ssSet(SS_ROOM, v); }}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        onSelectProject={(v) => { setSelectedProject(v); ssSet(SS_PROJECT, v); }}
        onSelectBranch={(v) => { setSelectedBranch(v); ssSet(SS_BRANCH, v); }}
        onSearchChange={setSearchQuery}
        onDeleteRoom={handleDeleteRoom}
      />
      {/* Resize handle */}
      {!sidebarCollapsed && (
        <div
          onMouseDown={onDragStart}
          className="w-1 cursor-col-resize hover:bg-blue-500/40 active:bg-blue-500/60 transition-colors shrink-0"
        />
      )}
      <ChatView
        room={selectedRoom}
        roomName={
          [...active, ...archived].find((r) => r.id === selectedRoom)?.name ?? selectedRoom
        }
        roomBranch={[...active, ...archived].find((r) => r.id === selectedRoom)?.branch}
        roomProject={[...active, ...archived].find((r) => r.id === selectedRoom)?.project}
        isLive={isLive}
        reader={readerId}
        onSelectProject={(p) => { setSelectedProject(p); ssSet(SS_PROJECT, p); setSelectedBranch(null); ssSet(SS_BRANCH, null); }}
        onSelectBranch={(b) => {
          const proj = [...active, ...archived].find((r) => r.id === selectedRoom)?.project ?? null;
          setSelectedProject(proj); ssSet(SS_PROJECT, proj);
          setSelectedBranch(b); ssSet(SS_BRANCH, b);
        }}
      />
    </div>
  );
}
