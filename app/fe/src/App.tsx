import "./index.css";
import { useState, useMemo, useCallback, useRef } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatView } from "./components/ChatView";
import { useChatrooms } from "./hooks/useChatrooms";
import { useProjects } from "./hooks/useProjects";
import { useSearch } from "./hooks/useSearch";

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 500;
const SIDEBAR_DEFAULT = 280;

export default function App() {
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const { active, archived, loading } = useChatrooms(
    selectedProject ?? undefined,
    selectedBranch ?? undefined
  );
  const projects = useProjects(active, archived);
  const { result: searchResult, loading: searchLoading } = useSearch(
    searchQuery,
    selectedProject ?? undefined
  );

  const [selectedRoom, setSelectedRoom] = useState<string | null>(null);
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

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      <Sidebar
        active={active}
        archived={archived}
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
        onSelectRoom={setSelectedRoom}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        onSelectProject={setSelectedProject}
        onSelectBranch={setSelectedBranch}
        onSearchChange={setSearchQuery}
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
        isLive={isLive}
      />
    </div>
  );
}
