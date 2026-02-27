const KNOWN_COLORS: Record<string, string> = {
  architect: "#8B5CF6",
  pm: "#3B82F6",
  "frontend-dev": "#10B981",
  "backend-dev": "#F59E0B",
  qa: "#EF4444",
  security: "#DC2626",
  devops: "#6366F1",
  coderabbit: "#F97316",
  gemini: "#06B6D4",
  codex: "#A855F7",
  designer: "#EC4899",
  "test-strategist": "#14B8A6",
};

// Always returns a 6-digit hex color (compatible with hex alpha append)
export function getRoleColor(role: string): string {
  const normalized = role.toLowerCase().replace(/\s+/g, "-");

  // Exact match
  if (KNOWN_COLORS[normalized]) return KNOWN_COLORS[normalized];

  // Prefix match: "codex-reviewer" → "codex", "gemini-reviewer" → "gemini"
  for (const key of Object.keys(KNOWN_COLORS)) {
    if (normalized.startsWith(key)) return KNOWN_COLORS[key];
  }

  // Deterministic hash fallback — convert HSL to hex so alpha append works
  const hash = [...normalized].reduce((acc, c) => acc * 31 + c.charCodeAt(0), 0);
  const h = ((hash % 360) + 360) % 360;
  return hslToHex(h, 70, 60);
}

function hslToHex(h: number, s: number, l: number): string {
  s /= 100;
  l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}
