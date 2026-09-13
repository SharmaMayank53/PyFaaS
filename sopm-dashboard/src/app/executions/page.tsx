"use client";

import { useState } from "react";
import { useExecutions } from "@/hooks/useQueries";
import { useDashboardStore } from "@/store";
import { Card, Table, Thead, Th, Tbody, Tr, Td, StatusBadge, Button, EmptyState, Spinner } from "@/components/ui";
import { formatRelative, formatDuration, truncate } from "@/lib/utils";
import { RefreshCw, ChevronRight } from "lucide-react";
import { ExecutionDrawer } from "@/components/execution/ExecutionDrawer";
import { CopyId } from "@/components/execution/CopyId";
import type { Execution } from "@/types";

export default function ExecutionsPage() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [failureFilter, setFailureFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [selected, setSelected] = useState<Execution | null>(null);

  const { data, isLoading, refetch, isFetching } = useExecutions({
    page,
    size: 25,
    status: statusFilter || undefined,
    failure_kind: failureFilter || undefined,
    source: sourceFilter || undefined,
  });

  const { liveExecutions } = useDashboardStore();
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / 25);
  const items = data?.items ?? [];
  const liveItems = Array.from(liveExecutions.values()).filter((le) => !items.find((i) => i.id === le.id));
  const merged = [...liveItems, ...items];

  return (
    <div className="space-y-5">
      <ExecutionDrawer executionId={selected?.id ?? null} initialExecution={selected} onClose={() => setSelected(null)} />

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Executions</h1>
          <p className="mt-1 text-sm text-text-muted">
            {isLoading ? "Loading..." : `${total} total`}
            {liveItems.length > 0 && <span className="ml-2 text-accent">+{liveItems.length} live</span>}
          </p>
        </div>
        <button onClick={() => refetch()} className="text-text-muted transition-colors hover:text-text-primary" title="Refresh">
          <RefreshCw size={15} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      <div className="flex gap-3">
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="rounded-lg bg-bg-raised px-3 py-2 text-sm text-text-primary ring-1 ring-white/10 focus:outline-none focus:ring-accent/100"
        >
          <option value="">All status</option>
          <option value="RUNNING">Running</option>
          <option value="COMPLETED">Completed</option>
          <option value="FAILED">Failed</option>
          <option value="TIMED_OUT">Timed out</option>
          <option value="QUEUED">Queued</option>
          <option value="PENDING">Pending</option>
        </select>
        <select
          value={failureFilter}
          onChange={(e) => { setFailureFilter(e.target.value); setPage(1); }}
          className="rounded-lg bg-bg-raised px-3 py-2 text-sm text-text-primary ring-1 ring-white/10 focus:outline-none focus:ring-accent/100"
        >
          <option value="">All failures</option>
          <option value="handler">Handler failures</option>
          <option value="infra,queue">Infra / queue failures</option>
        </select>
        <select
          value={sourceFilter}
          onChange={(e) => { setSourceFilter(e.target.value); setPage(1); }}
          className="rounded-lg bg-bg-raised px-3 py-2 text-sm text-text-primary ring-1 ring-white/10 focus:outline-none focus:ring-accent/100"
        >
          <option value="">All sources</option>
          <option value="function">Persistent functions</option>
          <option value="ephemeral">Ephemeral</option>
        </select>
      </div>

      <Card noPad>
        {isLoading ? (
          <div className="flex items-center justify-center py-16"><Spinner /></div>
        ) : !merged.length ? (
          <EmptyState message="No executions found" />
        ) : (
          <Table>
            <Thead>
              <tr>
                <Th>Execution</Th>
                <Th>Source</Th>
                <Th>Function</Th>
                <Th>Status</Th>
                <Th>Failure</Th>
                <Th>Version</Th>
                <Th>Duration</Th>
                <Th>Worker</Th>
                <Th>Started</Th>
                <Th></Th>
              </tr>
            </Thead>
            <Tbody>
              {merged.map((ex) => (
                <Tr key={ex.id} className="cursor-pointer" onClick={() => setSelected(ex)}>
                  <Td><CopyId value={ex.id} label="Copy execution ID" /></Td>
                  <Td><span className="text-xs text-text-muted">{ex.execution_type === "ephemeral" ? "Ephemeral" : "Function"}</span></Td>
                  <Td><span className="font-mono text-xs text-text-primary">{ex.function_name ?? (ex.execution_type === "ephemeral" ? "inline code" : truncate(ex.function_id ?? ex.id, 14))}</span></Td>
                  <Td><StatusBadge status={ex.status} /></Td>
                  <Td><span className="text-xs text-text-muted">{ex.failure_kind ?? "-"}</span></Td>
                  <Td><span className="font-mono text-xs text-text-muted">{ex.function_version_id ? truncate(ex.function_version_id, 8) : "-"}</span></Td>
                  <Td><span className="font-mono text-xs text-text-muted">{formatDuration(ex.duration_ms)}</span></Td>
                  <Td><span className="font-mono text-xs text-text-muted">{ex.worker_id ? truncate(ex.worker_id, 12) : "-"}</span></Td>
                  <Td><span className="text-xs text-text-muted">{formatRelative(ex.started_at ?? ex.created_at)}</span></Td>
                  <Td><ChevronRight size={13} className="text-text-muted" /></Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-text-muted">
          <span>Page {page} of {totalPages}</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
            <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</Button>
          </div>
        </div>
      )}
    </div>
  );
}




