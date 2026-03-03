import { useState } from "react";
import type { VersionStatus } from "../types";

const DISMISS_KEY_PREFIX = "tc:update-dismissed:";

export function UpdateBanner({ info }: { info: VersionStatus }) {
  const storageKey = `${DISMISS_KEY_PREFIX}${info.latest}`;
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(storageKey) === "1";
    } catch {
      return false;
    }
  });

  if (!info.update_available || dismissed) return null;

  return (
    <div
      className="bg-amber-500/15 border-b border-amber-500/30 px-4 py-2 text-sm text-amber-200 flex items-center justify-between"
      role="status"
    >
      <span>
        v{info.latest} available — run{" "}
        <code className="bg-amber-500/20 px-1.5 py-0.5 rounded text-xs">
          uv tool upgrade chatnut
        </code>{" "}
        to update
      </span>
      <button
        onClick={() => {
          setDismissed(true);
          try { localStorage.setItem(storageKey, "1"); } catch {}
        }}
        className="text-amber-400 hover:text-amber-200 ml-4 text-lg leading-none"
        aria-label="Dismiss update notification"
      >
        {"\u00d7"}
      </button>
    </div>
  );
}
