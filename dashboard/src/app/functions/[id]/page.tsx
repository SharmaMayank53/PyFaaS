"use client";

import { useActivateFunctionVersion, useDeleteFunction, useFunctionDetail, useFunctionVersions, useExecutions, useExecuteFunction, useUpdateFunctionCanary } from "@/hooks/useQueries";
import { Card, Table, Thead, Th, Tbody, Tr, Td, Badge, StatusBadge, Button, Spinner, EmptyState } from "@/components/ui";
import { formatRelative, formatDuration, formatBytes } from "@/lib/utils";
import { Play, ArrowLeft, Trash2, GitBranch, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ExecutionDrawer } from "@/components/execution/ExecutionDrawer";
import { CopyId } from "@/components/execution/CopyId";
import type { Execution } from "@/types";

export default function FunctionDetailPage({ params }: { params: { id: string } }) {
  const { id } = params;
  const router = useRouter();
  const { data: fn, isLoading } = useFunctionDetail(id);
  const { data: versions, isLoading: versionsLoading } = useFunctionVersions(id);
  const { data: executions, isLoading: exLoading } = useExecutions({ function_id: id, size: 10 });
  const execMut = useExecuteFunction();
  const deleteMut = useDeleteFunction();
  const activateMut = useActivateFunctionVersion();
  const canaryMut = useUpdateFunctionCanary();
  const [canaryVersionId, setCanaryVersionId] = useState("");
  const [canaryPercent, setCanaryPercent] = useState("10");
  const [drawerExecutionId, setDrawerExecutionId] = useState<string | null>(null);
  const [drawerInitialExecution, setDrawerInitialExecution] = useState<Execution | null>(null);

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  async function handleDelete() {
    if (!fn) return;
    if (!window.confirm(`Delete function "${fn.name}"? This removes its versions and artifacts, and linked schedules/execution history may be removed by database cascade.`)) return;
    await deleteMut.mutateAsync(fn.id);
    router.push("/functions");
  }


  async function handleActivate(versionId: string, versionNumber: number) {
    if (!fn) return;
    if (!window.confirm(`Activate v${versionNumber} for "${fn.name}"? Future executions will use this version immediately and canary traffic will be cleared.`)) return;
    await activateMut.mutateAsync({ functionId: fn.id, versionId });
  }

  async function handleSetCanary() {
    if (!fn) return;
    const selectedVersionId = canaryVersionId || fn.canary_version_id || "";
    const percent = Number(canaryPercent || fn.canary_percent || 0);
    if (!selectedVersionId || !Number.isFinite(percent) || percent <= 0 || percent > 100) return;
    const version = versions?.items.find((item) => item.id === selectedVersionId);
    if (!window.confirm(`Send ${percent}% of future executions for "${fn.name}" to v${version?.version_number ?? "?"}?`)) return;
    await canaryMut.mutateAsync({ functionId: fn.id, canary_version_id: selectedVersionId, canary_percent: percent });
  }

  async function handleClearCanary() {
    if (!fn) return;
    if (!window.confirm(`Clear canary traffic for "${fn.name}"?`)) return;
    await canaryMut.mutateAsync({ functionId: fn.id, canary_version_id: null, canary_percent: 0 });
    setCanaryVersionId("");
  }

  async function handlePromoteCanary() {
    if (!fn?.canary_version_id) return;
    if (!window.confirm(`Promote the canary version for "${fn.name}" to 100% and clear canary traffic?`)) return;
    await canaryMut.mutateAsync({ functionId: fn.id, canary_version_id: fn.canary_version_id, canary_percent: 100 });
    setCanaryVersionId("");
  }
  async function handleExecute() {
    if (!fn) return;
    const execution = await execMut.mutateAsync({ id: fn.id });
    setDrawerInitialExecution(execution);
    setDrawerExecutionId(execution.id);
  }

  if (!fn) {
    return (
      <div className="text-center py-16">
        <p className="text-text-secondary text-sm">Function not found</p>
        <Link href="/functions" className="text-accent text-sm hover:underline mt-2 block">
          ← Back to functions
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <ExecutionDrawer executionId={drawerExecutionId} initialExecution={drawerInitialExecution} onClose={() => setDrawerExecutionId(null)} />
      {/* Header */}
      <div>
        <Link
          href="/functions"
          className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary mb-3 w-fit"
        >
          <ArrowLeft size={12} /> Functions
        </Link>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-text-primary">{fn.name}</h1>
            <div className="mt-2"><CopyId value={fn.id} label="Copy function ID" short={18} /></div>
            {fn.description && (
              <p className="text-sm text-text-secondary mt-1">{fn.description}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="danger" size="sm" loading={deleteMut.isPending} onClick={handleDelete}>
              <Trash2 size={12} />
              Delete
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={execMut.isPending}
              onClick={handleExecute}
              disabled={fn.status !== "ACTIVE"}
            >
              <Play size={12} />
              Execute
            </Button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Metadata */}
        <Card className="lg:col-span-1">
          <p className="text-xs font-medium text-text-secondary uppercase tracking-wider mb-3">
            Details
          </p>
          <div className="space-y-3 text-xs">
            {[
              ["Runtime", fn.runtime],
              ["Status", null],
              ["Active Version", fn.active_version ? `v${fn.active_version.version_number}` : "None"],
              ["Timeout", fn.active_version ? `${fn.active_version.timeout}s` : "—"],
              ["Memory", fn.active_version ? `${fn.active_version.memory_mb} MB` : "—"],
              ["Artifact Size", formatBytes(fn.active_version?.artifact_size)],
              ["Entrypoint", fn.active_version?.entrypoint ?? "—"],
              ["Created", formatRelative(fn.created_at)],
              ["Updated", formatRelative(fn.updated_at)],
            ].map(([label, value]) => (
              <div key={label as string} className="flex justify-between gap-2">
                <span className="text-text-secondary">{label}</span>
                {label === "Status" ? (
                  <Badge variant={fn.status === "ACTIVE" ? "success" : "warning"}>
                    {fn.status}
                  </Badge>
                ) : (
                  <span className="font-mono text-text-primary text-right truncate max-w-[160px]">
                    {value as string}
                  </span>
                )}
              </div>
            ))}
          </div>

          {/* Tags */}
          {Object.keys(fn.tags).length > 0 && (
            <div className="mt-4 pt-4 border-t border-border">
              <p className="text-xs text-text-secondary uppercase tracking-wider mb-2">Tags</p>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(fn.tags).map(([k, v]) => (
                  <span key={k} className="font-mono text-[10px] bg-bg-base border border-border rounded px-1.5 py-0.5 text-text-secondary">
                    {k}={v}
                  </span>
                ))}
              </div>
            </div>
          )}
        </Card>

        {/* Recent executions */}
        <Card noPad className="lg:col-span-2">
          <div className="px-4 pt-4 pb-3 border-b border-border">
            <p className="text-xs font-medium text-text-secondary uppercase tracking-wider">
              Recent Executions
            </p>
          </div>
          {exLoading ? (
            <div className="flex justify-center py-8">
              <Spinner />
            </div>
          ) : !executions?.items.length ? (
            <EmptyState message="No executions yet" />
          ) : (
            <Table>
              <Thead>
                <tr>
                  <Th>Status</Th>
                  <Th>Duration</Th>
                  <Th>Worker</Th>
                  <Th>When</Th>
                </tr>
              </Thead>
              <Tbody>
                {executions.items.map((ex) => (
                  <Tr key={ex.id} className="cursor-pointer" onClick={() => { setDrawerInitialExecution(ex); setDrawerExecutionId(ex.id); }}>
                    <Td>
                      <Link href={`/executions/${ex.id}`}>
                        <StatusBadge status={ex.status} />
                      </Link>
                    </Td>
                    <Td>
                      <span className="font-mono text-xs text-text-secondary">
                        {formatDuration(ex.duration_ms)}
                      </span>
                    </Td>
                    <Td>
                      <span className="font-mono text-xs text-text-secondary">
                        {ex.worker_id ?? "—"}
                      </span>
                    </Td>
                    <Td>
                      <span className="text-xs text-text-secondary">
                        {formatRelative(ex.created_at)}
                      </span>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </Card>
      </div>
      <Card noPad>
        <div className="flex items-center justify-between border-b border-border px-4 pb-3 pt-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-text-secondary">Versions & Canary</p>
            <p className="mt-1 text-xs text-text-muted">Rollback by activating an older version, or split traffic to a canary.</p>
          </div>
          {fn.canary_version_id && fn.canary_percent > 0 && (
            <Badge variant="warning">Canary {fn.canary_percent}%</Badge>
          )}
        </div>

        <div className="grid gap-4 p-4 lg:grid-cols-[1fr_320px]">
          <div>
            {versionsLoading ? (
              <div className="flex justify-center py-8"><Spinner /></div>
            ) : !versions?.items.length ? (
              <EmptyState message="No versions uploaded" />
            ) : (
              <Table>
                <Thead>
                  <tr>
                    <Th>Version</Th>
                    <Th>Entrypoint</Th>
                    <Th>Limits</Th>
                    <Th>Uploaded</Th>
                    <Th></Th>
                  </tr>
                </Thead>
                <Tbody>
                  {versions.items.map((version) => {
                    const isActive = version.id === fn.active_version_id;
                    const isCanary = version.id === fn.canary_version_id;
                    return (
                      <Tr key={version.id}>
                        <Td>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs text-text-primary">v{version.version_number}</span>
                            {isActive && <Badge variant="success">Active</Badge>}
                            {isCanary && <Badge variant="warning">Canary</Badge>}
                          </div>
                        </Td>
                        <Td><span className="font-mono text-xs text-text-muted">{version.entrypoint}</span></Td>
                        <Td><span className="text-xs text-text-muted">{version.timeout}s / {version.memory_mb} MB</span></Td>
                        <Td><span className="text-xs text-text-muted">{formatRelative(version.created_at)}</span></Td>
                        <Td>
                          {!isActive && (
                            <Button size="sm" variant="outline" loading={activateMut.isPending} onClick={() => handleActivate(version.id, version.version_number)}>
                              <RotateCcw size={12} /> Activate
                            </Button>
                          )}
                        </Td>
                      </Tr>
                    );
                  })}
                </Tbody>
              </Table>
            )}
          </div>

          <div className="space-y-3 border-t border-border pt-4 lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0">
            <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-text-secondary">
              <GitBranch size={13} /> Canary Split
            </div>
            <select
              value={canaryVersionId || fn.canary_version_id || ""}
              onChange={(e) => setCanaryVersionId(e.target.value)}
              className="w-full rounded-lg bg-bg-raised px-3 py-2 text-sm text-text-primary ring-1 ring-white/10 focus:outline-none focus:ring-accent/100"
            >
              <option value="">Select version</option>
              {versions?.items.filter((version) => version.id !== fn.active_version_id).map((version) => (
                <option key={version.id} value={version.id}>v{version.version_number}</option>
              ))}
            </select>
            <input
              value={canaryPercent}
              onChange={(e) => setCanaryPercent(e.target.value)}
              type="number"
              min={1}
              max={100}
              className="w-full rounded-lg bg-bg-raised px-3 py-2 text-sm text-text-primary ring-1 ring-white/10 focus:outline-none focus:ring-accent/100"
            />
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="primary" loading={canaryMut.isPending} onClick={handleSetCanary}>Set Canary</Button>
              <Button size="sm" variant="outline" disabled={!fn.canary_version_id} loading={canaryMut.isPending} onClick={handlePromoteCanary}>Promote</Button>
              <Button size="sm" variant="outline" disabled={!fn.canary_version_id} loading={canaryMut.isPending} onClick={handleClearCanary}>Clear</Button>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}








