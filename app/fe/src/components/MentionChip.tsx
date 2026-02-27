import { getRoleColor } from "../utils/roleColors";

export function MentionChip({ name }: { name: string }) {
  const color = getRoleColor(name);
  return (
    <span
      className="inline-flex items-center text-xs font-medium px-1.5 py-0.5 rounded mx-0.5 align-baseline"
      style={{
        backgroundColor: color + "20",
        color: color,
      }}
    >
      @{name}
    </span>
  );
}
