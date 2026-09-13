"use client";

import { useDashboard, useQueueMetrics } from "@/hooks/useQueries";
import { useDashboardStore } from "@/store";
import { MetricCard, Spinner } from "@/components/ui";
import { RecentExecutions, RecentFailures } from "@/components/dashboard/ActivityPanels";
import { ExecutionTrendChart, QueueDepthChart } from "@/components/charts";
import { RefreshCw, Wifi, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";

function useQueueHistory(current: number | null) {
  const [history, setHistory] = useState<Array<{ time: string; depth: number }>>([]);

  useEffect(() => {
    if (current === null) return;
    const now = new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
    setHistory((prev) => [...prev.slice(-29), { time: now, depth: current }]);
  }, [current]);

  return history;
}

function hasUsefulTrend(data: Array<{ total: number }>) {
  return data.reduce((sum, item) => sum + item.total, 0) >= 2;
}

export default function DashboardPage() {
  const { data, isLoading, error, refetch, isFetching } = useDashboard();
  const { data: queue } = useQueueMetrics();
  const { wsConnected, queueDepth: liveQueueDepth } = useDashboardStore();

  const currentQueueDepth = liveQueueDepth ?? queue?.queue_depth ?? data?.overview.queue_depth ?? null;
  const queueHistory = useQueueHistory(currentQueueDepth);
  const successRate = data?.metrics.success_rate ?? 0;
  const trend = data?.metrics.executions_last_24h ?? [];

  if (error) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <p className="text-sm text-error">Failed to load dashboard data.</p>
        <button onClick={() => refetch()} className="text-sm text-accent hover:underline">Retry</button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Operations Dashboard</h1>
          <p className="mt-1 text-sm text-text-muted">
            {data?.timestamp ? `Last updated ${new Date(data.timestamp).toLocaleTimeString()}` : "Loading..."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-text-muted">
            {wsConnected ? <><Wifi size={12} className="text-success" /> Live</> : <><WifiOff size={12} className="text-error" /> Polling</>}
          </div>
          <button onClick={() => refetch()} disabled={isFetching} className="flex items-center gap-1.5 text-xs text-text-muted transition-colors hover:text-text-primary">
            <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard label="Active Functions" value={isLoading ? "-" : (data?.overview.active_functions ?? 0)} loading={isLoading} />
        <MetricCard label="Running Now" value={isLoading ? "-" : (data?.overview.running_executions ?? 0)} accent="text-accent" loading={isLoading} />
        <MetricCard
          label="Queue Depth"
          value={currentQueueDepth ?? 0}
          accent={(currentQueueDepth ?? 0) > 50 ? "text-error" : (currentQueueDepth ?? 0) > 10 ? "text-warning" : "text-text-primary"}
          loading={isLoading}
        />
        <MetricCard
          label="Success Rate"
          value={isLoading ? "-" : `${successRate.toFixed(1)}%`}
          accent={successRate >= 90 ? "text-success" : successRate >= 70 ? "text-warning" : "text-error"}
          sub={`${data?.overview.failed_executions_24h ?? 0} failures in 24h`}
          loading={isLoading}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {hasUsefulTrend(trend) ? (
          <ExecutionTrendChart data={trend} loading={isLoading} />
        ) : (
          <div className="rounded-2xl bg-bg-surface p-6 text-sm text-text-muted shadow-card ring-1 ring-white/10">
            <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Execution Trend</p>
            <p className="mt-8 text-center">Not enough executions yet.</p>
          </div>
        )}
        <QueueDepthChart data={queueHistory} loading={false} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <RecentExecutions executions={data?.recent_executions ?? []} />
        <RecentFailures failures={data?.recent_failures ?? []} />
      </div>
    </div>
  );
}
