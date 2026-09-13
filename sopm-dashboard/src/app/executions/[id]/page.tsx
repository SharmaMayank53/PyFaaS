"use client";

import { useEffect, useState } from "react";
import { useExecutionDetail, useExecutionLogs } from "@/hooks/useQueries";
import { Card, StatusBadge, Spinner, Button } from "@/components/ui";
import { formatDuration, formatTimestamp, cn } from "@/lib/utils";
import { ArrowLeft, ChevronDown, Download } from "lucide-react";
import Link from "next/link";
import { ResultRenderer } from "@/components/execution/ResultRenderer";
import { CopyId } from "@/components/execution/CopyId";

function LogLine({ log, i }: { log: any; i: number }) {
  return (
    <div className="grid grid-cols-[2rem_1fr] gap-3 px-4 py-1 hover:bg-white/[0.03]">
      <span className="select-none text-right text-[10px] leading-5 text-text-faint">{i + 1}</span>
      <span className={cn("break-all font-mono text-[11px] leading-5", log.level === "ERROR" ? "text-error" : log.level === "WARN" ? "text-warning" : "text-text-primary")}>
        <span className="mr-2 text-text-muted">[{log.level}]</span>
        {log.message}
      </span>
    </div>
  );
}

export default function ExecutionDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const { data: exec, isLoading } = useExecutionDetail(id);
  const { data: logs, isLoading: logsLoading } = useExecutionLogs(id, exec?.status);
  const [logsOpen, setLogsOpen] = useState(false);

  useEffect(() => {
    setLogsOpen(false);
  }, [id]);

  if (isLoading) return <div className="flex justify-center py-16"><Spinner /></div>;
  if (!exec) return (
    <div className="py-16 text-center">
      <p className="text-sm text-text-muted">Execution not found</p>
      <Link href="/executions" className="mt-2 block text-sm text-accent hover:underline">Back</Link>
    </div>
  );

  function handleDownload() {
    if (!logs?.length) return;
    const text = logs.map((l: any) => `[${l.timestamp}] [${l.level}] ${l.message}`).join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `sopm-exec-${id}.log`;
    a.click();
  }

  return (
    <div className="space-y-5">
      <div>
        <Link href="/executions" className="mb-3 flex w-fit items-center gap-1.5 text-xs text-text-muted hover:text-text-primary">
          <ArrowLeft size={12} /> Executions
        </Link>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-text-primary">Execution</h1>
            <div className="mt-2"><CopyId value={id} label="Copy execution ID" short={18} /></div>
            <p className="mt-2 text-sm text-text-muted">{exec.function_name ?? "Unknown function"}</p>
          </div>
          <StatusBadge status={exec.status} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Duration", value: formatDuration(exec.duration_ms) },
          { label: "Worker", value: exec.worker_id ?? "-" },
          { label: "Started", value: formatTimestamp(exec.started_at) },
          { label: "Completed", value: formatTimestamp(exec.completed_at) },
        ].map(({ label, value }) => (
          <Card key={label} className="py-3">
            <p className="text-xs text-text-muted">{label}</p>
            <p className="mt-1 truncate font-mono text-xs text-text-primary">{value}</p>
          </Card>
        ))}
      </div>

      <Card elevated>
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-muted">Result</p>
        <ResultRenderer execution={exec} />
      </Card>

      <details
        open={logsOpen}
        onToggle={(event) => setLogsOpen(event.currentTarget.open)}
        className="group rounded-2xl bg-bg-surface shadow-card ring-1 ring-white/5"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium text-text-secondary hover:text-text-primary">
          View logs
          <ChevronDown size={15} className="transition-transform group-open:rotate-180" />
        </summary>
        <div className="border-t border-white/10 py-3">
          <div className="mb-2 flex justify-end px-3">
            <Button size="sm" variant="ghost" onClick={handleDownload} disabled={!logs?.length}>
              <Download size={12} />
              Export
            </Button>
          </div>
          {logsLoading ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : !logs?.length ? (
            <p className="py-8 text-center text-xs text-text-muted">No logs captured</p>
          ) : (
            <div className="max-h-[500px] overflow-y-auto py-2">{logs.map((log: any, i: number) => <LogLine key={i} log={log} i={i} />)}</div>
          )}
        </div>
      </details>
    </div>
  );
}