import { useState } from "react";
import type { VersionStatus } from "../types";

export function UpdateBanner({ info }: { info: VersionStatus }) {
  const [dismissed, setDismissed] = useState(false);

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
        onClick={() => setDismissed(true)}
        className="text-amber-400 hover:text-amber-200 ml-4 text-lg leading-none"
        aria-label="Dismiss update notification"
      >
        {"\u00d7"}
      </button>
    </div>
  );
}
