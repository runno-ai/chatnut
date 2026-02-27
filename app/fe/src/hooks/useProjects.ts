import { useState, useEffect } from "react";

export function useProjects() {
  const [projects, setProjects] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/projects", { signal: controller.signal })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((data: unknown) => {
        const list = Array.isArray(data) ? data : (data as Record<string, unknown>)?.projects;
        setProjects(Array.isArray(list) ? list.filter((p): p is string => typeof p === "string") : []);
      })
      .catch((err) => {
        if (err.name !== "AbortError") console.warn("Failed to fetch projects:", err);
      });
    return () => controller.abort();
  }, []);

  return projects;
}
