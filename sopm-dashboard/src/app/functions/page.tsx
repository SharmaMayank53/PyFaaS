"use client";

import { useRef, useState } from "react";
import {
  useFunctions,
  useExecutions,
  useCreateFunction,
  useDeleteFunction,
  useExecuteFunction,
  useUploadFunctionVersion,
} from "@/hooks/useQueries";
import {
  Card, Table, Thead, Th, Tbody, Tr, Td,
  Badge, Button, Input, EmptyState, Spinner
} from "@/components/ui";
import { formatRelative, formatBytes, cn } from "@/lib/utils";
import { AlertTriangle, CircleCheck, CircleHelp, Search, Play, Trash2, RefreshCw, Eye, Upload, XCircle } from "lucide-react";
import Link from "next/link";
import { ExecutionDrawer } from "@/components/execution/ExecutionDrawer";
import { CopyId } from "@/components/execution/CopyId";
import type { Execution, ExecutionStatus, FunctionStatus } from "@/types";

function fnStatusVariant(s: FunctionStatus) {
  return s === "ACTIVE" ? "success" : s === "INACTIVE" ? "warning" : "default";
}


type FunctionHealth = "Healthy" | "Degraded" | "Failing" | "Unknown";

const PROBLEM_STATUSES: ExecutionStatus[] = ["FAILED", "TIMED_OUT", "CANCELLED"];

function getFunctionHealth(functionId: string, executions: Execution[] = []): FunctionHealth {
  const recent = executions
    .filter((execution) => execution.function_id === functionId)
    .filter((execution) => execution.status === "COMPLETED" || PROBLEM_STATUSES.includes(execution.status))
    .slice(0, 10);

  if (recent.length === 0) return "Unknown";

  const problemCount = recent.filter((execution) => PROBLEM_STATUSES.includes(execution.status)).length;
  if (problemCount === 0) return "Healthy";

  const lastThree = recent.slice(0, 3);
  if (problemCount > recent.length / 2 || (lastThree.length === 3 && lastThree.every((execution) => PROBLEM_STATUSES.includes(execution.status)))) {
    return "Failing";
  }

  return "Degraded";
}

function FunctionHealthIndicator({ health }: { health: FunctionHealth }) {
  const Icon = health === "Healthy" ? CircleCheck : health === "Degraded" ? AlertTriangle : health === "Failing" ? XCircle : CircleHelp;
  const styles = {
    Healthy: "text-success bg-success/10 ring-success/20",
    Degraded: "text-warning bg-warning/10 ring-warning/20",
    Failing: "text-error bg-error/10 ring-error/20",
    Unknown: "text-text-muted bg-bg-raised ring-white/10",
  }[health];

  return (
    <span className={cn("inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1", styles)} title={`Function health: ${health}`}>
      <Icon size={12} />
      {health}
    </span>
  );
}
function uploadErrorMessage(err: any) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg ?? item?.message ?? JSON.stringify(item))
      .join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return err?.message ?? "Upload failed.";
}

export default function FunctionsPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [entrypoint, setEntrypoint] = useState("handler.handler");
  const [archive, setArchive] = useState<File | null>(null);
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");
  const [deleteError, setDeleteError] = useState("");
  const [deleteSuccess, setDeleteSuccess] = useState("");
  const [deletingFunctionId, setDeletingFunctionId] = useState<string | null>(null);
  const [drawerExecutionId, setDrawerExecutionId] = useState<string | null>(null);
  const [drawerInitialExecution, setDrawerInitialExecution] = useState<Execution | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const { data, isLoading, refetch } = useFunctions({
    page,
    size: 20,
    search: debouncedSearch || undefined,
    status: statusFilter || undefined,
  });
  const { data: recentExecutions } = useExecutions({ page: 1, size: 100, source: "function" });

  const createMut = useCreateFunction();
  const uploadMut = useUploadFunctionVersion();
  const deleteMut = useDeleteFunction();
  const execMut = useExecuteFunction();

  function handleSearchChange(v: string) {
    setSearch(v);
    clearTimeout((handleSearchChange as any)._t);
    (handleSearchChange as any)._t = setTimeout(() => {
      setDebouncedSearch(v);
      setPage(1);
    }, 300);
  }

  async function handleDelete(id: string, name: string) {
    if (deletingFunctionId) return;
    if (!window.confirm(`Delete function "${name}"? This removes versions, artifacts, and schedules. Completed execution history is preserved.`)) return;

    setDeleteError("");
    setDeleteSuccess("");
    setDeletingFunctionId(id);
    try {
      await deleteMut.mutateAsync(id);
      setDeleteSuccess(`Deleted ${name}`);
    } catch (err: any) {
      setDeleteError(uploadErrorMessage(err));
    } finally {
      setDeletingFunctionId(null);
    }
  }

  async function handleExecute(id: string) {
    const execution = await execMut.mutateAsync({ id });
    setDrawerInitialExecution(execution);
    setDrawerExecutionId(execution.id);
  }

  async function handleCreateAndUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setFormError("");
    setFormSuccess("");

    if (!name.trim()) {
      setFormError("Function name is required.");
      return;
    }
    if (!archive) {
      setFormError("Choose a ZIP archive to upload.");
      return;
    }

    let createdFunctionId: string | null = null;

    try {
      const fn = await createMut.mutateAsync({
        name: name.trim(),
        description: description.trim() || undefined,
      });
      createdFunctionId = fn.id;
      await uploadMut.mutateAsync({
        id: fn.id,
        archive,
        entrypoint: entrypoint.trim() || "handler.handler",
        timeout: 300,
        memory_mb: 128,
      });
      setName("");
      setDescription("");
      setEntrypoint("handler.handler");
      setArchive(null);
      formRef.current?.reset();
      setFormSuccess(`Uploaded ${archive.name}`);
      refetch();
    } catch (err: any) {
      if (createdFunctionId) {
        await deleteMut.mutateAsync(createdFunctionId).catch(() => undefined);
      }
      setFormError(uploadErrorMessage(err));
    }
  }

  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / 20);
  const isCreating = createMut.isPending || uploadMut.isPending;

  return (
    <div className="space-y-5">
      <ExecutionDrawer executionId={drawerExecutionId} initialExecution={drawerInitialExecution} onClose={() => setDrawerExecutionId(null)} />
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Functions</h1>
          <p className="text-xs text-text-secondary mt-0.5">
            {isLoading ? "Loading…" : `${total} function${total !== 1 ? "s" : ""}`}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="text-text-secondary hover:text-text-primary transition-colors"
        >
          <RefreshCw size={14} />
        </button>
      </div>

      <Card elevated>
        <form ref={formRef} onSubmit={handleCreateAndUpload} className="grid gap-4 lg:grid-cols-[1fr_1.2fr_auto] lg:items-end">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs text-text-secondary">Function name</label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="hello-world"
                pattern="[a-zA-Z0-9_-]+"
                required
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-text-secondary">Entrypoint</label>
              <Input
                value={entrypoint}
                onChange={(e) => setEntrypoint(e.target.value)}
                placeholder="handler.handler"
                required
              />
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-[1fr_1fr]">
            <div>
              <label className="mb-1.5 block text-xs text-text-secondary">Description</label>
              <Input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-text-secondary">ZIP archive</label>
              <Input
                type="file"
                accept=".zip,application/zip,application/x-zip-compressed"
                onChange={(e) => setArchive(e.target.files?.[0] ?? null)}
                required
                className="file:mr-3 file:rounded file:border-0 file:bg-accent file:px-2 file:py-1 file:text-xs file:text-white"
              />
            </div>
          </div>

          <Button type="submit" variant="primary" loading={isCreating} className="justify-center">
            <Upload size={14} />
            Upload ZIP
          </Button>

          {formError && (
            <p className="lg:col-span-3 text-xs text-error">{formError}</p>
          )}
          {formSuccess && (
            <p className="lg:col-span-3 text-xs text-success">{formSuccess}</p>
          )}
        </form>
      </Card>

      {(deleteError || deleteSuccess) && (
        <div className={cn("rounded-lg border px-3 py-2 text-xs", deleteError ? "border-error/30 bg-error/10 text-error" : "border-success/30 bg-success/10 text-success")}>{deleteError || deleteSuccess}</div>
      )}
      {/* Filters */}
      <div className="flex gap-3 items-center">
        <div className="relative flex-1 max-w-sm">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
          <Input
            placeholder="Search functions…"
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-8"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="rounded border border-border bg-bg-base px-3 py-2 text-sm text-text-primary
            focus:outline-none focus:border-accent"
        >
          <option value="">All status</option>
          <option value="ACTIVE">Active</option>
          <option value="INACTIVE">Inactive</option>
          <option value="DEPRECATED">Deprecated</option>
        </select>
      </div>

      {/* Table */}
      <Card noPad>
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Spinner />
          </div>
        ) : !data?.items.length ? (
          <EmptyState message="No functions found" />
        ) : (
          <Table>
            <Thead>
              <tr>
                <Th>Name</Th>
                <Th>Runtime</Th>
                <Th>Version</Th>
                <Th>Status</Th>
                <Th>Version</Th>
                <Th>Health</Th>
                <Th>Deployed</Th>
                <Th>Actions</Th>
              </tr>
            </Thead>
            <Tbody>
              {data.items.map((fn) => (
                <Tr key={fn.id}>
                  <Td>
                    <Link
                      href={`/functions/${fn.id}`}
                      className="text-sm font-semibold text-text-primary hover:text-accent"
                    >
                      {fn.name}
                    </Link>
                    <div className="mt-1"><CopyId value={fn.id} label="Copy function ID" /></div>
                    {fn.description && (
                      <p className="text-xs text-text-secondary mt-0.5 truncate max-w-[200px]">
                        {fn.description}
                      </p>
                    )}
                  </Td>
                  <Td>
                    <span className="font-mono text-xs text-text-secondary">{fn.runtime}</span>
                  </Td>
                  <Td>
                    <span className="font-mono text-xs text-text-secondary">
                      {fn.active_version ? `v${fn.active_version.version_number}` : "—"}
                    </span>
                  </Td>
                  <Td>
                    <Badge variant={fnStatusVariant(fn.status)}>{fn.status}</Badge>
                  </Td>
                  <Td>
                    <span className="font-mono text-xs text-text-secondary">
                      {formatBytes(fn.active_version?.artifact_size)}
                    </span>
                  </Td>
                  <Td>
                    <FunctionHealthIndicator health={getFunctionHealth(fn.id, recentExecutions?.items)} />
                  </Td>
                  <Td>
                    <span className="text-xs text-text-secondary">
                      {formatRelative(fn.updated_at)}
                    </span>
                  </Td>
                  <Td>
                    <div className="flex items-center gap-1">
                      <Link href={`/functions/${fn.id}`}>
                        <Button size="sm" variant="ghost" title="View details">
                          <Eye size={12} />
                        </Button>
                      </Link>
                      <Button
                        size="sm"
                        variant="ghost"
                        title="Execute"
                        loading={execMut.isPending}
                        onClick={() => handleExecute(fn.id)}
                        disabled={fn.status !== "ACTIVE"}
                      >
                        <Play size={12} className="text-success" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        title="Delete"
                        loading={deletingFunctionId === fn.id}
                        disabled={Boolean(deletingFunctionId)}
                        onClick={() => handleDelete(fn.id, fn.name)}
                      >
                        <Trash2 size={12} className="text-error" />
                      </Button>
                    </div>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-text-secondary">
          <span>
            Page {page} of {totalPages} ({total} total)
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}






