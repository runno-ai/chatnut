import { useState, useRef, useEffect, type ReactNode } from "react";

interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
  disabled?: boolean;
  className?: string;
  icon?: ReactNode;
}

export function Select({ value, onChange, options, placeholder, disabled, className = "", icon }: SelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const selected = options.find((o) => o.value === value);
  const label = selected?.label ?? placeholder;

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setOpen(!open)}
        onKeyDown={(e) => { if (e.key === "Escape" && open) { setOpen(false); e.stopPropagation(); } }}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={`w-full flex items-center gap-1.5 bg-gray-800 text-xs rounded px-2 py-1.5 border border-gray-700 focus:border-blue-500 focus:outline-none transition-colors ${
          disabled ? "opacity-40 cursor-default" : "cursor-pointer hover:border-gray-600"
        } ${value ? "text-gray-300" : "text-gray-500"}`}
      >
        {icon && <span className="shrink-0 text-gray-500">{icon}</span>}
        <span className="truncate flex-1 text-left">{label}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" className={`shrink-0 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="M2 3.5l3 3 3-3" stroke="currentColor" strokeWidth="1.2" fill="none" />
        </svg>
      </button>
      {open && (
        <div className="absolute left-0 right-0 top-full mt-0.5 z-50 bg-gray-800 border border-gray-700 rounded shadow-lg max-h-48 overflow-y-auto">
          <button
            type="button"
            onClick={() => { onChange(""); setOpen(false); }}
            className={`w-full text-left px-2 py-1.5 text-xs hover:bg-gray-700 transition-colors ${
              !value ? "text-blue-400" : "text-gray-300"
            }`}
          >
            {placeholder}
          </button>
          {options.map((o) => (
            <button
              type="button"
              key={o.value}
              onClick={() => { onChange(o.value); setOpen(false); }}
              className={`w-full text-left px-2 py-1.5 text-xs hover:bg-gray-700 transition-colors ${
                o.value === value ? "text-blue-400" : "text-gray-300"
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
