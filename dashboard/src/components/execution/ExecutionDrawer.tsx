"use client";

import { useEffect, useState } from "react";
import { X, ChevronDown, Download } from "lucide-react";
import { Button, Spinner, StatusBadge } from "@/components/ui";
import { useExecutionDetail, useExecutionLogs } from "@/hooks/useQueries";
import { formatDuration, formatTimestamp, cn } from "@/lib/utils";
import type { Execution } from "@/types";
import { CopyId } from "@/components/execution/CopyId";
import { ResultRenderer } from "@/components/execution/ResultRenderer";

function executionSubtitle(exec: Execution | null): string {
  if (!exec) return "Waiting for execution data";
  if (exec.status === "COMPLETED") {
    if (exec.duration_ms != null) return `Ran in ${formatDuration(exec.duration_ms)}`;
    if (exec.completed_at) return `Completed ${formatTimestamp(exec.completed_at)}`;
    return "Execution completed";
  }
  if (exec.status === "FAILED") return exec.error_message ? "Execution failed with an error" : "Execution failed";
  if (exec.status === "TIMED_OUT") return "Execution timed out";
  if (exec.status === "CANCELLED") return "Execution cancelled";
  if (exec.status === "RUNNING") return exec.started_at ? `Started ${formatTimestamp(exec.started_at)}` : "Execution is running";
  if (exec.status === "QUEUED" || exec.status === "PENDING") return "Execution is queued";
  return exec.function_name ?? "Execution data loaded";
}

function LogLine({ log, i }: { log: any; i: number }) {
  return (
    <div className="grid grid-cols-[2rem_1fr] gap-3 px-3 py-1 hover:bg-white/[0.03]">
      <span className="select-none text-right text-[10px] leading-5 text-text-faint">{i + 1}</span>
      <span
        className={cn(
          "break-all font-mono text-[11px] leading-5",
          log.level === "ERROR" ? "text-error" : log.level === "WARN" ? "text-warning" : "text-text-primary"
        )}
      >
        <span className="mr-2 text-text-muted">[{log.level}]</span>
        {log.message}
      </span>
    </div>
  );
}

export function ExecutionDrawer({
  executionId,
  initialExecution,
  onClose,
}: {
  executionId: string | null;
  initialExecution?: Execution | null;
  onClose: () => void;
}) {
  const { data: fetched, isLoading } = useExecutionDetail(executionId ?? "");
  const exec = fetched ?? initialExecution ?? null;
  const { data: logs, isLoading: logsLoading } = useExecutionLogs(executionId ?? "", exec?.status);
  const open = Boolean(executionId);
  const [logsOpen, setLogsOpen] = useState(false);

  useEffect(() => {
    setLogsOpen(false);
  }, [executionId]);

  if (!open) return null;

  function downloadLogs() {
    if (!logs?.length || !executionId) return;
    const text = logs.map((l: any) => `[${l.timestamp}] [${l.level}] ${l.message}`).join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `sopm-exec-${executionId}.log`;
    a.click();
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col bg-bg-overlay shadow-drawer">
        <div className="flex items-start justify-between border-b border-white/10 px-6 py-5">
          <div className="min-w-0 space-y-2">
            <div className="flex items-center gap-2">
              {exec ? <StatusBadge status={exec.status} /> : <span className="text-xs text-text-muted">Starting</span>}
              {isLoading && <Spinner />}
            </div>
            <div>
              <h2 className="text-lg font-semibold text-text-primary">Execution result</h2>
              <p className="mt-1 text-sm text-text-muted">{executionSubtitle(exec)}</p>
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} title="Close">
            <X size={16} />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {!exec && isLoading ? (
            <div className="flex min-h-72 items-center justify-center"><Spinner /></div>
          ) : (
            <div className="space-y-5">
              <ResultRenderer execution={exec} />

              <div className="grid grid-cols-2 gap-3 rounded-2xl bg-bg-surface p-4 text-xs shadow-card">
                <div>
                  <p className="text-text-muted">Execution</p>
                  <div className="mt-1"><CopyId value={exec?.id ?? executionId} /></div>
                </div>
                <div>
                  <p className="text-text-muted">Function</p>
                  <div className="mt-1"><CopyId value={exec?.function_id} /></div>
                </div>
                <div>
                  <p className="text-text-muted">Duration</p>
                  <p className="mt-1 font-mono text-text-primary">{formatDuration(exec?.duration_ms)}</p>
                </div>
                <div>
                  <p className="text-text-muted">Worker</p>
                  <p className="mt-1 font-mono text-text-primary">{exec?.worker_id ?? "-"}</p>
                </div>
                <div>
                  <p className="text-text-muted">Started</p>
                  <p className="mt-1 font-mono text-text-primary">{formatTimestamp(exec?.started_at)}</p>
                </div>
                <div>
                  <p className="text-text-muted">Completed</p>
                  <p className="mt-1 font-mono text-text-primary">{formatTimestamp(exec?.completed_at)}</p>
                </div>
              </div>

              <details
                open={logsOpen}
                onToggle={(event) => setLogsOpen(event.currentTarget.open)}
                className="group rounded-2xl bg-bg-surface shadow-card"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium text-text-secondary hover:text-text-primary">
                  View logs
                  <ChevronDown size={15} className="transition-transform group-open:rotate-180" />
                </summary>
                <div className="border-t border-white/10 py-3">
                  <div className="mb-2 flex justify-end px-3">
                    <Button size="sm" variant="ghost" onClick={downloadLogs} disabled={!logs?.length}>
                      <Download size={12} />
                      Export
                    </Button>
                  </div>
                  {logsLoading ? (
                    <div className="flex justify-center py-8"><Spinner /></div>
                  ) : !logs?.length ? (
                    <p className="py-8 text-center text-xs text-text-muted">No logs captured</p>
                  ) : (
                    <div className="max-h-80 overflow-auto pb-2">{logs.map((log: any, i: number) => <LogLine key={i} log={log} i={i} />)}</div>
                  )}
                </div>
              </details>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}