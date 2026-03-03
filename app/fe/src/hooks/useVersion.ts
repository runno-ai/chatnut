import { useState, useEffect } from "react";
import type { VersionStatus } from "../types";

export function useVersion(): VersionStatus | null {
  const [info, setInfo] = useState<VersionStatus | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/status", { signal: controller.signal })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => setInfo(data))
      .catch(() => {});
    return () => controller.abort();
  }, []);

  return info;
}
