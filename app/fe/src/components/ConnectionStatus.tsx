interface ConnectionStatusProps {
  status: "connecting" | "connected" | "disconnected";
}

export function ConnectionStatus({ status }: ConnectionStatusProps) {
  if (status === "connected") {
    return (
      <span className="text-xs text-green-500/70 flex items-center gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
        Live
      </span>
    );
  }

  if (status === "connecting") {
    return (
      <span className="text-xs text-yellow-500 flex items-center gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 animate-pulse" />
        Connecting...
      </span>
    );
  }

  return (
    <span className="text-xs text-red-400 flex items-center gap-1">
      <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
      Reconnecting...
    </span>
  );
}
