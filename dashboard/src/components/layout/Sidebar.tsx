"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Zap,
  PlayCircle,
  CalendarClock,
  ScrollText,
  KeyRound,
  Server,
  LogOut,
  Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore, useDashboardStore } from "@/store";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/functions", label: "Functions", icon: Zap },
  { href: "/executions", label: "Executions", icon: PlayCircle },
  { href: "/schedules", label: "Schedules", icon: CalendarClock },
  { href: "/logs", label: "Logs", icon: ScrollText },
  { href: "/keys", label: "API Keys", icon: KeyRound },
  { href: "/cluster", label: "Cluster", icon: Server },
];

export function Sidebar() {
  const pathname = usePathname();
  const { username, logout } = useAuthStore();
  const { wsConnected, liveEvents } = useDashboardStore();
  const navItems = NAV.map(({ href, label, icon: Icon }) => ({
    href,
    label,
    Icon,
    active: href === "/" ? pathname === "/" : pathname.startsWith(href),
  }));

  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 shrink-0 flex-col border-r border-border bg-bg-panel md:flex">
        <div className="flex items-center gap-2.5 border-b border-border px-5 py-4">
          <div className="flex h-6 w-6 items-center justify-center rounded bg-accent">
            <Activity size={13} className="text-white" />
          </div>
          <span className="font-mono text-sm font-bold tracking-tight text-text-primary">PyFaaS</span>
        </div>

        <nav className="space-y-0.5 px-2 py-3">
          {navItems.map(({ href, label, Icon, active }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-accent/10 text-accent"
                  : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
              )}
            >
              <Icon size={15} />
              {label}
            </Link>
          ))}
        </nav>

        <div className="mt-auto space-y-3 border-t border-border p-3">
          <div className="flex items-center gap-2 px-2">
            <span className={cn("inline-flex h-1.5 w-1.5 rounded-full", wsConnected ? "bg-success" : "bg-error")} />
            <span className="text-xs text-text-secondary">{wsConnected ? "Live" : "Disconnected"}</span>
            {liveEvents.length > 0 && <span className="ml-auto font-mono text-xs text-accent">{liveEvents.length}</span>}
          </div>

          <div className="flex items-center justify-between px-2">
            <span className="truncate font-mono text-xs text-text-secondary">{username ?? "-"}</span>
            <button onClick={logout} className="text-text-secondary transition-colors hover:text-error" title="Logout">
              <LogOut size={13} />
            </button>
          </div>
        </div>
      </aside>

      <header className="fixed inset-x-0 top-0 z-30 border-b border-border bg-bg-panel md:hidden">
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-accent">
              <Activity size={13} className="text-white" />
            </div>
            <span className="font-mono text-sm font-bold tracking-tight text-text-primary">PyFaaS</span>
          </Link>
          <div className="flex min-w-0 items-center gap-2">
            <span className={cn("inline-flex h-1.5 w-1.5 shrink-0 rounded-full", wsConnected ? "bg-success" : "bg-error")} />
            <span className="truncate font-mono text-xs text-text-secondary">{username ?? "-"}</span>
            <button onClick={logout} className="text-text-secondary transition-colors hover:text-error" title="Logout">
              <LogOut size={13} />
            </button>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2">
          {navItems.map(({ href, label, Icon, active }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex shrink-0 items-center gap-2 rounded px-3 py-2 text-xs transition-colors",
                active ? "bg-accent/10 text-accent" : "text-text-secondary hover:bg-white/5 hover:text-text-primary"
              )}
            >
              <Icon size={14} />
              {label}
            </Link>
          ))}
        </nav>
      </header>
    </>
  );
}