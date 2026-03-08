import {
  Blocks,
  Clock3,
  LayoutDashboard,
  Moon,
  Orbit,
  ScrollText,
  Settings,
  Sun,
} from "lucide-react";

const items = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "reasoning", label: "Reasoning", icon: Orbit },
  { id: "templates", label: "Templates", icon: Blocks },
  { id: "history", label: "History", icon: Clock3 },
  { id: "audit-log", label: "Audit Log", icon: ScrollText },
  { id: "settings", label: "Settings", icon: Settings },
];

interface SidebarProps {
  activeItem: string;
  onSelect: (item: string) => void;
  theme: "dark" | "light";
  onToggleTheme: () => void;
}

export function Sidebar({ activeItem, onSelect, theme, onToggleTheme }: SidebarProps) {
  const logoSrc = theme === "dark" ? "/images/logo_light.png" : "/images/logo_darkpng.png";

  return (
    <aside className="relative flex w-[96px] flex-col border-r border-[var(--mw-border)] bg-[var(--mw-page)] px-3 py-4 text-[var(--mw-text)]">
      <div className="mb-8 flex h-16 flex-col items-center justify-center">
        <img src={logoSrc} alt="MindWeave" className="h-9 w-9 object-contain" />
        <div className="mt-1 text-[9px] uppercase tracking-[0.32em] text-[var(--mw-subtle)]">MindWeave</div>
      </div>

      <nav className="flex flex-1 flex-col gap-2.5">
        {items.map(({ id, label, icon: Icon }) => {
          const active = activeItem === id;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onSelect(id)}
              className={`group relative flex min-h-[68px] flex-col items-center justify-center gap-2 rounded-[18px] border transition ${
                active
                  ? "border-[var(--mw-border)] bg-[var(--mw-panel)] text-[var(--mw-text)]"
                  : "border-transparent bg-transparent text-[var(--mw-subtle)] hover:border-[var(--mw-border)] hover:bg-[var(--mw-panel)] hover:text-[var(--mw-text)]"
              }`}
            >
              {active && <span className="absolute left-0 top-4 h-9 w-px bg-[var(--mw-accent)]" />}
              <Icon size={18} strokeWidth={1.6} />
              <span className="text-[10px] tracking-[0.08em]">{label}</span>
            </button>
          );
        })}
      </nav>

      <div className="mt-5 flex flex-col items-start gap-3">
        <button
          type="button"
          onClick={onToggleTheme}
          className="flex w-full items-center justify-between rounded-full border border-[var(--mw-border)] bg-[var(--mw-panel)] px-2 py-2 text-[var(--mw-muted)] transition hover:text-[var(--mw-text)]"
          aria-label="Toggle theme"
        >
          <span
            className={`flex h-8 w-8 items-center justify-center rounded-full transition ${
              theme === "light" ? "bg-[var(--mw-accent-soft)] text-[var(--mw-accent)]" : "bg-transparent"
            }`}
          >
            <Sun size={14} strokeWidth={1.8} />
          </span>
          <span
            className={`flex h-8 w-8 items-center justify-center rounded-full transition ${
              theme === "dark" ? "bg-[var(--mw-accent-soft)] text-[var(--mw-accent)]" : "bg-transparent"
            }`}
          >
            <Moon size={14} strokeWidth={1.8} />
          </span>
        </button>
        <div className="flex h-11 w-full items-center justify-center text-[var(--mw-subtle)]">
          <span className="font-mono text-[11px]">01</span>
        </div>
      </div>
    </aside>
  );
}
