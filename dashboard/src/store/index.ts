import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Execution, HealthComponents, Overview, WsEvent } from "@/types";

// ─── Auth Store ────────────────────────────────────────────────────────────

interface AuthState {
  token: string | null;
  username: string | null;
  setToken: (token: string, username: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: typeof window !== "undefined" ? localStorage.getItem("sopm_token") : null,
      username: null,
      isAuthenticated: typeof window !== "undefined" ? Boolean(localStorage.getItem("sopm_token")) : false,
      setToken: (token, username) => {
        localStorage.setItem("sopm_token", token);
        document.cookie = `sopm_token=${token}; path=/; max-age=3600; SameSite=Lax`;
        set({ token, username, isAuthenticated: true });
      },
      logout: () => {
        localStorage.removeItem("sopm_token");
        localStorage.removeItem("sopm-auth");
        document.cookie = "sopm_token=; path=/; max-age=0; SameSite=Lax";
        set({ token: null, username: null, isAuthenticated: false });
      },
    }),
    {
      name: "sopm-auth",
      partialize: (s) => ({
        token: s.token,
        username: s.username,
      }),
    }
  )
);

// ─── Real-time Dashboard Store ─────────────────────────────────────────────

interface LiveEvent {
  id: string;
  type: string;
  message: string;
  timestamp: string;
}

interface DashboardState {
  wsConnected: boolean;
  liveEvents: LiveEvent[];
  liveExecutions: Map<string, Execution>;
  queueDepth: number | null;
  setWsConnected: (v: boolean) => void;
  pushWsEvent: (event: WsEvent) => void;
  upsertLiveExecution: (exec: Partial<Execution> & { id: string }) => void;
  setQueueDepth: (depth: number) => void;
  clearEvents: () => void;
}

export const useDashboardStore = create<DashboardState>()((set, get) => ({
  wsConnected: false,
  liveEvents: [],
  liveExecutions: new Map(),
  queueDepth: null,

  setWsConnected: (v) => set({ wsConnected: v }),

  pushWsEvent: (event) => {
    const { type, payload, timestamp } = event;

    // Update derived state
    if (type === "queue_depth_changed" && "depth" in payload) {
      set({ queueDepth: payload.depth as number });
    }

    if (type === "execution_started" && "execution_id" in payload) {
      get().upsertLiveExecution({
        id: payload.execution_id as string,
        status: "RUNNING",
        function_name: (payload.function_name as string) ?? null,
        created_at: timestamp,
        worker_id: (payload.worker_id as string) ?? null,
        function_id: null,
        duration_ms: null,
        started_at: timestamp,
        completed_at: null,
        error_message: null,
      });
    }

    if (type === "execution_completed" && "execution_id" in payload) {
      get().upsertLiveExecution({
        id: payload.execution_id as string,
        status: (payload.status as Execution["status"]) ?? "COMPLETED",
        duration_ms: payload.duration_ms as number,
        completed_at: timestamp,
      });
    }

    if (type === "execution_failed" && "execution_id" in payload) {
      get().upsertLiveExecution({
        id: payload.execution_id as string,
        status: "FAILED",
        error_message: payload.error as string,
        completed_at: timestamp,
      });
    }

    // Append to live event log (cap at 100)
    const message = buildEventMessage(type, payload);
    set((s) => ({
      liveEvents: [
        { id: crypto.randomUUID(), type, message, timestamp },
        ...s.liveEvents,
      ].slice(0, 100),
    }));
  },

  upsertLiveExecution: (partial) =>
    set((s) => {
      const next = new Map(s.liveExecutions);
      const existing = next.get(partial.id) ?? ({} as Execution);
      next.set(partial.id, { ...existing, ...partial } as Execution);
      return { liveExecutions: next };
    }),

  setQueueDepth: (depth) => set({ queueDepth: depth }),
  clearEvents: () => set({ liveEvents: [] }),
}));

function buildEventMessage(type: string, payload: Record<string, unknown>): string {
  switch (type) {
    case "execution_started":
      return `Execution started: ${payload.execution_id ?? "—"} (${payload.function_name ?? "unknown"})`;
    case "execution_completed":
      return `Execution completed: ${payload.execution_id ?? "—"} in ${payload.duration_ms ?? "?"}ms`;
    case "execution_failed":
      return `Execution FAILED: ${payload.execution_id ?? "—"} — ${payload.error ?? "no message"}`;
    case "deployment_started":
      return `Deploy started: ${payload.function_name ?? "?"} v${payload.version_number}`;
    case "deployment_completed":
      return `Deploy complete: ${payload.function_name ?? "?"} v${payload.version_number}`;
    case "worker_online":
      return `Worker online: ${payload.worker_id}`;
    case "worker_offline":
      return `Worker offline: ${payload.worker_id}`;
    case "queue_depth_changed":
      return `Queue depth: ${payload.depth}`;
    case "health_changed":
      return `Health change: ${payload.component} → ${payload.status}`;
    default:
      return type;
  }
}


