// src/hooks/useProjects.ts
import { useMemo } from "react";
import type { ChatroomInfo } from "../types";

export function useProjects(active: ChatroomInfo[], archived: ChatroomInfo[]) {
  return useMemo(() => {
    const all = [...active, ...archived];
    return [...new Set(all.map((r) => r.project))].sort();
  }, [active, archived]);
}
