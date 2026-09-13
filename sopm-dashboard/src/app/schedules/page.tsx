"use client";

import { useMemo, useState } from "react";
import { useCreateSchedule, useDeleteSchedule, useFunctions, useSchedules, useUpdateSchedule } from "@/hooks/useQueries";
import { Badge, Button, Card, EmptyState, Input, Spinner, Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui";
import { formatRelative, formatTimestamp, truncate } from "@/lib/utils";
import { CalendarClock, ChevronDown, Edit2, Pause, Play, RefreshCw, Trash2, X } from "lucide-react";
import type { Schedule, ScheduleStatus } from "@/types";

function scheduleVariant(status: ScheduleStatus) {
  if (status === "ACTIVE") return "success";
  if (status === "PAUSED") return "warning";
  return "default";
}

function parsePayload(raw: string): Record<string, unknown> {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Payload must be a JSON object.");
  return parsed as Record<string, unknown>;
}

function cronLabel(expression: string) {
  const examples: Record<string, string> = {
    "*/5 * * * *": "Every 5 minutes",
    "0 * * * *": "Hourly",
    "0 9 * * *": "Daily at 09:00",
    "0 9 * * 1": "Mondays at 09:00",
  };
  return examples[expression] ?? expression;
}

function errorMessage(err: any) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg ?? JSON.stringify(item)).join("; ");
  return err?.message ?? "Schedule request failed.";
}

export default function SchedulesPage() {
  const [functionId, setFunctionId] = useState("");
  const [name, setName] = useState("");
  const [cron, setCron] = useState("*/5 * * * *");
  const [payload, setPayload] = useState("{}");
  const [showPayload, setShowPayload] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");

  const { data: functions, isLoading: functionsLoading } = useFunctions({ size: 100 });
  const { data: schedules, isLoading, refetch, isFetching } = useSchedules({ size: 50 });
  const createMut = useCreateSchedule();
  const updateMut = useUpdateSchedule();
  const deleteMut = useDeleteSchedule();

  const functionNameById = useMemo(() => new Map(functions?.items.map((fn) => [fn.id, fn.name] as const) ?? []), [functions?.items]);
  const items = schedules?.items ?? [];
  const hasFunctions = (functions?.items.length ?? 0) > 0;
  const busy = createMut.isPending || updateMut.isPending || deleteMut.isPending;

  function resetForm() {
    setEditing(null);
    setFunctionId("");
    setName("");
    setCron("*/5 * * * *");
    setPayload("{}");
    setShowPayload(false);
    setFormError("");
    setFormSuccess("");
  }

  function beginEdit(schedule: Schedule) {
    setEditing(schedule);
    setFunctionId(schedule.function_id);
    setName(schedule.name);
    setCron(schedule.cron_expression);
    setPayload(JSON.stringify(schedule.payload ?? {}, null, 2));
    setShowPayload(Object.keys(schedule.payload ?? {}).length > 0);
    setFormError("");
    setFormSuccess("");
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setFormError("");
    setFormSuccess("");

    if (!functionId) {
      setFormError("Choose a function to automate.");
      return;
    }

    try {
      const parsedPayload = parsePayload(payload);
      if (editing) {
        await updateMut.mutateAsync({ id: editing.id, name: name.trim(), cron_expression: cron.trim(), payload: parsedPayload });
        setFormSuccess("Schedule updated.");
        resetForm();
        return;
      }

      await createMut.mutateAsync({
        function_id: functionId,
        name: name.trim() || `${functionNameById.get(functionId) ?? "function"}-schedule`,
        cron_expression: cron.trim(),
        payload: parsedPayload,
      });
      setName("");
      setPayload("{}");
      setShowPayload(false);
      setFormSuccess("Schedule created.");
    } catch (err: any) {
      setFormError(errorMessage(err));
    }
  }

  async function toggleSchedule(id: string, status: ScheduleStatus) {
    await updateMut.mutateAsync({ id, status: status === "ACTIVE" ? "PAUSED" : "ACTIVE" });
  }

  async function removeSchedule(id: string, scheduleName: string) {
    if (!confirm(`Delete schedule "${scheduleName}"?`)) return;
    await deleteMut.mutateAsync(id);
    if (editing?.id === id) resetForm();
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Schedules</h1>
          {items.length > 0 && <p className="mt-1 text-sm text-text-muted">{items.length} automation{items.length !== 1 ? "s" : ""}</p>}
        </div>
        <button onClick={() => refetch()} className="text-text-muted transition-colors hover:text-text-primary" title="Refresh schedules">
          <RefreshCw size={15} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      <Card elevated>
        <form onSubmit={handleSubmit} className="grid gap-4 xl:grid-cols-[1fr_1fr_1fr_auto] xl:items-end">
          <div>
            <label className="mb-1.5 block text-xs text-text-muted">Function</label>
            <select
              value={functionId}
              onChange={(e) => setFunctionId(e.target.value)}
              disabled={functionsLoading || !hasFunctions || Boolean(editing)}
              className="w-full rounded-lg bg-bg-raised px-3 py-2 text-sm text-text-primary ring-1 ring-white/10 focus:outline-none focus:ring-accent/60 disabled:opacity-50"
            >
              <option value="">{functionsLoading ? "Loading functions..." : "Choose function"}</option>
              {functions?.items.map((fn) => <option key={fn.id} value={fn.id}>{fn.name}</option>)}
            </select>
          </div>

          <div>
            <label className="mb-1.5 block text-xs text-text-muted">Schedule name</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="nightly-sync" />
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <label className="block text-xs text-text-muted">Cron</label>
              <span className="text-[11px] text-text-faint" title="Examples: */5 * * * * every 5 minutes; 0 * * * * hourly; 0 9 * * * daily at 09:00">Examples</span>
            </div>
            <Input value={cron} onChange={(e) => setCron(e.target.value)} placeholder="*/5 * * * *" required />
          </div>

          <div className="flex gap-2">
            <Button type="submit" variant="primary" loading={createMut.isPending || updateMut.isPending} disabled={!hasFunctions} className="flex-1 justify-center">
              <CalendarClock size={14} />
              {editing ? "Save" : "Create"}
            </Button>
            {editing && <Button type="button" variant="ghost" onClick={resetForm} title="Cancel edit"><X size={14} /></Button>}
          </div>

          <div className="xl:col-span-4">
            <button type="button" onClick={() => setShowPayload((v) => !v)} className="flex items-center gap-2 text-xs text-text-muted hover:text-text-primary">
              <ChevronDown size={13} className={showPayload ? "rotate-180" : ""} />
              Add payload (optional)
            </button>
            {showPayload && (
              <textarea
                value={payload}
                onChange={(e) => setPayload(e.target.value)}
                rows={4}
                className="mt-2 w-full rounded-lg bg-bg-raised px-3 py-2 font-mono text-xs text-text-primary ring-1 ring-white/10 placeholder:text-text-faint focus:outline-none focus:ring-accent/60"
                placeholder='{"name":"SOPM"}'
              />
            )}
          </div>

          {!hasFunctions && !functionsLoading && <p className="xl:col-span-4 text-xs text-warning">Upload a function before creating an automation.</p>}
          {formError && <p className="xl:col-span-4 text-xs text-error">{formError}</p>}
          {formSuccess && <p className="xl:col-span-4 text-xs text-success">{formSuccess}</p>}
        </form>
      </Card>

      <Card noPad>
        {isLoading ? (
          <div className="flex items-center justify-center py-16"><Spinner /></div>
        ) : !items.length ? (
          <EmptyState message="No schedules found" />
        ) : (
          <Table>
            <Thead>
              <tr>
                <Th>Name</Th>
                <Th>Function</Th>
                <Th>Cron</Th>
                <Th>Status</Th>
                <Th>Next run</Th>
                <Th>Last triggered</Th>
                <Th>Actions</Th>
              </tr>
            </Thead>
            <Tbody>
              {items.map((schedule) => (
                <Tr key={schedule.id}>
                  <Td>
                    <p className="font-mono text-xs text-text-primary">{schedule.name}</p>
                    <p className="mt-0.5 font-mono text-xs text-text-muted">{truncate(schedule.id, 14)}</p>
                  </Td>
                  <Td><span className="font-mono text-xs text-text-muted">{functionNameById.get(schedule.function_id) ?? truncate(schedule.function_id, 14)}</span></Td>
                  <Td><span className="font-mono text-xs text-text-primary">{cronLabel(schedule.cron_expression)}</span></Td>
                  <Td><Badge variant={scheduleVariant(schedule.status)}>{schedule.status}</Badge></Td>
                  <Td><div className="text-xs text-text-muted"><p>{formatRelative(schedule.next_run_at)}</p><p className="font-mono">{formatTimestamp(schedule.next_run_at)}</p></div></Td>
                  <Td><div className="text-xs text-text-muted"><p>{schedule.last_run_at ? formatRelative(schedule.last_run_at) : "No run yet"}</p>{schedule.last_run_at && <p className="font-mono">{formatTimestamp(schedule.last_run_at)}</p>}</div></Td>
                  <Td>
                    <div className="flex items-center gap-1">
                      <Button size="sm" variant="ghost" title="Edit" onClick={() => beginEdit(schedule)} disabled={busy}><Edit2 size={12} /></Button>
                      <Button size="sm" variant="ghost" title={schedule.status === "ACTIVE" ? "Pause" : "Resume"} loading={updateMut.isPending} onClick={() => toggleSchedule(schedule.id, schedule.status)}>
                        {schedule.status === "ACTIVE" ? <Pause size={12} className="text-warning" /> : <Play size={12} className="text-success" />}
                      </Button>
                      <Button size="sm" variant="ghost" title="Delete" loading={deleteMut.isPending} disabled={busy} onClick={() => removeSchedule(schedule.id, schedule.name)}><Trash2 size={12} className="text-error" /></Button>
                    </div>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
