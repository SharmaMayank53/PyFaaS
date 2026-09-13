"use client";

import { useDetailedHealth, useWorkerMetrics } from "@/hooks/useQueries";
import { Badge, Card, EmptyState, HealthDot, Spinner, Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui";
import { cn, formatRelative, healthColor, truncate } from "@/lib/utils";
import type { HealthStatus } from "@/types";
import { AlertTriangle, RefreshCw } from "lucide-react";

function HealthRow({ label, status }: { label: string; status: HealthStatus }) {
  return (
    <div className="flex items-center justify-between py-2.5 last:pb-0">
      <span className="text-sm text-text-primary">{label}</span>
      <div className="flex items-center gap-2.5">
        <HealthDot status={status} />
        <span className={cn("font-mono text-xs", healthColor(status))}>{status}</span>
      </div>
    </div>
  );
}

export default function ClusterPage() {
  const { data, isLoading, refetch, isFetching } = useDetailedHealth();
  const { data: workers, isLoading: workersLoading } = useWorkerMetrics();
  const components = data?.components;
  const overall = data?.overall ?? "unhealthy";
  const overallColor = overall === "healthy" ? "text-success" : overall === "degraded" ? "text-warning" : "text-error";
  const staleWorkers = workers ? workers.total - workers.online : 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Cluster</h1>
          <p className="mt-1 text-sm text-text-muted">Infrastructure health, orchestration, and worker heartbeat.</p>
        </div>
        <button onClick={() => refetch()} className="text-text-muted transition-colors hover:text-text-primary" title="Refresh cluster health">
          <RefreshCw size={15} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      {!isLoading && (
        <div
          className={cn(
            "flex items-center gap-3 rounded-2xl px-4 py-3 shadow-card ring-1",
            overall === "healthy"
              ? "bg-success/10 text-success ring-success/20"
              : overall === "degraded"
              ? "bg-warning/10 text-warning ring-warning/20"
              : "bg-error/10 text-error ring-error/20"
          )}
        >
          {overall !== "healthy" && <AlertTriangle size={15} />}
          <p className={cn("text-sm font-semibold", overallColor)}>System is <span className="font-mono uppercase">{overall}</span></p>
          {data?.timestamp && <span className="ml-auto text-xs text-text-muted">Checked {new Date(data.timestamp).toLocaleTimeString()}</span>}
        </div>
      )}

      {isLoading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-muted">Infrastructure</p>
            {components ? (
              <div className="divide-y divide-white/10">
                <HealthRow label="API Gateway" status={components.api} />
                <HealthRow label="PostgreSQL" status={components.postgres} />
                <HealthRow label="Redis" status={components.redis} />
                <HealthRow label="MinIO Object Storage" status={components.minio} />
              </div>
            ) : <EmptyState message="No health data" />}
          </Card>

          <Card>
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-muted">Orchestration</p>
            {components ? (
              <div className="divide-y divide-white/10">
                <HealthRow label="Kubernetes API" status={components.kubernetes} />
                <HealthRow label="Runner Pool" status={components.runner_pool} />
              </div>
            ) : <EmptyState message="No orchestration data" />}
          </Card>

          <Card noPad className="lg:col-span-2">
            <div className="flex items-center justify-between px-4 py-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Workers</p>
                <p className="mt-1 text-xs text-text-muted">
                  {workersLoading ? "Loading heartbeat data" : `${workers?.online ?? 0}/${workers?.total ?? 0} online${staleWorkers ? `, ${staleWorkers} stale` : ""}`}
                </p>
              </div>
              {staleWorkers > 0 && <Badge variant="error">{staleWorkers} stale</Badge>}
            </div>
            {workersLoading ? (
              <div className="flex justify-center py-10"><Spinner /></div>
            ) : !workers?.workers.length ? (
              <EmptyState message="No workers registered" />
            ) : (
              <Table>
                <Thead>
                  <tr>
                    <Th>Worker ID</Th>
                    <Th>Status</Th>
                    <Th>Last heartbeat</Th>
                    <Th>Age</Th>
                  </tr>
                </Thead>
                <Tbody>
                  {workers.workers.map((worker) => (
                    <Tr key={worker.worker_id}>
                      <Td><span className="font-mono text-xs text-text-primary">{truncate(worker.worker_id, 28)}</span></Td>
                      <Td><Badge variant={worker.status === "online" ? "success" : "error"}>{worker.status}</Badge></Td>
                      <Td><span className="text-xs text-text-muted">{formatRelative(worker.last_heartbeat)}</span></Td>
                      <Td><span className={cn("font-mono text-xs", worker.age_seconds > 120 ? "text-error" : "text-text-muted")}>{worker.age_seconds.toFixed(0)}s</span></Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
