// src/hooks/useSearch.ts
import { useState, useEffect, useRef } from "react";
import type { SearchResult } from "../types";

export function useSearch(query: string, project?: string) {
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!query || query.length < 2) {
      setResult(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);

    timeoutRef.current = setTimeout(() => {
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      const params = new URLSearchParams({ q: query });
      if (project) params.set("project", project);
      fetch(`/api/search?${params}`, { signal: abortRef.current.signal })
        .then((res) => res.json())
        .then((data) => {
          setResult(data);
          setLoading(false);
        })
        .catch((e) => {
          if (e instanceof Error && e.name === "AbortError") return;
          setResult(null);
          setLoading(false);
        });
    }, 300);

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      abortRef.current?.abort();
    };
  }, [query, project]);

  return { result, loading };
}
