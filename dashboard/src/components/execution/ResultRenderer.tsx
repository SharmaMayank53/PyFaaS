"use client";

import { ReactNode, useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn, formatTimestamp } from "@/lib/utils";
import type { Execution } from "@/types";

type JsonPrimitive = string | number | boolean | null;
type JsonObject = Record<string, unknown>;

const PRIMARY_FIELD_NAMES = new Set(["message", "summary", "title", "status", "state", "result", "return_value", "error"]);
const TIMESTAMP_KEY_PATTERN = /(^|_)(timestamp|created_at|updated_at|started_at|completed_at|time|date)$/i;
const ISO_TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;

function isRecord(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isPrimitive(value: unknown): value is JsonPrimitive {
  return value == null || ["string", "number", "boolean"].includes(typeof value);
}

function isPrimitiveArray(value: unknown): value is JsonPrimitive[] {
  return Array.isArray(value) && value.every(isPrimitive);
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function isTimestampField(key: string, value: unknown): value is string {
  return typeof value === "string" && TIMESTAMP_KEY_PATTERN.test(key) && ISO_TIMESTAMP_PATTERN.test(value) && !Number.isNaN(new Date(value).getTime());
}

function formatPrimitive(key: string, value: JsonPrimitive): string {
  if (value == null) return "-";
  if (isTimestampField(key, value)) return formatTimestamp(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function valuePreview(value: unknown): ReactNode {
  if (isPrimitive(value)) return String(value ?? "-");
  if (isPrimitiveArray(value)) return value.map((item) => String(item ?? "-")).join(", ");
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  if (isRecord(value)) return `${Object.keys(value).length} field${Object.keys(value).length === 1 ? "" : "s"}`;
  return String(value);
}

export function executionResultSummary(result: unknown): string | null {
  if (isPrimitive(result)) return result == null ? null : String(result);
  if (!isRecord(result)) return null;

  for (const key of ["message", "summary", "title", "return_value", "error", "status"]) {
    const value = result[key];
    if (isPrimitive(value) && value != null) return String(value);
  }

  const nested = result.result;
  if (isRecord(nested)) return executionResultSummary(nested);
  if (isPrimitive(nested) && nested != null) return String(nested);

  return null;
}

function PrimitivePill({ label, value, prominent = false }: { label: string; value: JsonPrimitive; prominent?: boolean }) {
  return (
    <div className={cn("rounded-xl bg-bg-raised/60 p-3 ring-1 ring-white/5", prominent && "bg-accent/10 ring-accent/20")}>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">{humanizeKey(label)}</p>
      <p className={cn("mt-1 whitespace-pre-wrap break-words text-text-primary", prominent ? "text-base font-semibold leading-6" : "text-sm")}>{formatPrimitive(label, value)}</p>
    </div>
  );
}

function PrimitiveArray({ label, values }: { label: string; values: JsonPrimitive[] }) {
  return (
    <section className="rounded-xl bg-bg-surface p-3 ring-1 ring-white/5">
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-text-muted">{humanizeKey(label)}</p>
      <div className="flex flex-wrap gap-1.5">
        {values.length ? (
          values.map((value, index) => (
            <span key={`${label}-${index}`} className="rounded-full bg-bg-raised px-2.5 py-1 text-xs text-text-secondary ring-1 ring-white/10">
              {formatPrimitive(label, value)}
            </span>
          ))
        ) : (
          <span className="text-xs text-text-muted">Empty list</span>
        )}
      </div>
    </section>
  );
}

function KeyValueRows({ entries, depth = 0 }: { entries: [string, unknown][]; depth?: number }) {
  return (
    <div className="divide-y divide-white/10 overflow-hidden rounded-lg ring-1 ring-white/5">
      {entries.map(([key, value]) => (
        <div key={key} className="grid gap-2 bg-bg-base/35 px-3 py-2 sm:grid-cols-[9rem_1fr]">
          <dt className="text-xs font-medium text-text-muted">{humanizeKey(key)}</dt>
          <dd className="min-w-0 text-sm text-text-primary">{renderNestedValue(key, value, depth)}</dd>
        </div>
      ))}
    </div>
  );
}

function ObjectCard({ label, value, depth = 0 }: { label: string; value: JsonObject; depth?: number }) {
  return (
    <section className="rounded-xl bg-bg-surface p-3 ring-1 ring-white/5">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-text-muted">{humanizeKey(label)}</p>
      <KeyValueRows entries={Object.entries(value)} depth={depth} />
    </section>
  );
}

function ObjectArrayTable({ label, values }: { label: string; values: JsonObject[] }) {
  const keys = Array.from(new Set(values.flatMap((item) => Object.keys(item))));
  const consistent = values.length > 0 && values.every((item) => keys.every((key) => key in item));

  if (!consistent || keys.length === 0 || keys.length > 8) {
    return (
      <section className="rounded-xl bg-bg-surface p-3 ring-1 ring-white/5">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-text-muted">{humanizeKey(label)}</p>
        <div className="space-y-2">
          {values.map((item, index) => <ObjectCard key={`${label}-${index}`} label={`Item ${index + 1}`} value={item} depth={1} />)}
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-xl bg-bg-surface p-3 ring-1 ring-white/5">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-text-muted">{humanizeKey(label)}</p>
      <div className="overflow-x-auto rounded-lg ring-1 ring-white/5">
        <table className="w-full min-w-max text-left text-sm">
          <thead className="bg-bg-base/60 text-xs uppercase tracking-wider text-text-muted">
            <tr>{keys.map((key) => <th key={key} className="px-3 py-2 font-semibold">{humanizeKey(key)}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {values.map((item, index) => (
              <tr key={`${label}-${index}`} className="bg-bg-base/25">
                {keys.map((key) => <td key={key} className="max-w-xs px-3 py-2 align-top text-text-primary">{renderNestedValue(key, item[key], 1)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function renderNestedValue(key: string, value: unknown, depth: number): ReactNode {
  if (isPrimitive(value)) return <span className="break-words">{formatPrimitive(key, value)}</span>;

  if (isPrimitiveArray(value)) {
    return value.length ? (
      <span className="break-words">{value.map((item) => formatPrimitive(key, item)).join(", ")}</span>
    ) : (
      <span className="text-text-muted">Empty list</span>
    );
  }

  if (Array.isArray(value) && value.every(isRecord)) {
    return depth >= 1 ? <span className="text-text-muted">{valuePreview(value)}</span> : <ObjectArrayTable label={key} values={value} />;
  }

  if (isRecord(value)) {
    return depth >= 1 ? <span className="text-text-muted">{valuePreview(value)}</span> : <ObjectCard label={key} value={value} depth={depth + 1} />;
  }

  return <span className="text-text-muted">Unsupported value</span>;
}

function StructuredResult({ result }: { result: unknown }) {
  if (isPrimitive(result)) {
    return (
      <div className="rounded-xl bg-bg-raised/70 p-4 shadow-inner-soft">
        <p className="whitespace-pre-wrap break-words text-lg font-medium leading-7 text-text-primary">{formatPrimitive("result", result)}</p>
      </div>
    );
  }

  if (Array.isArray(result)) {
    if (isPrimitiveArray(result)) return <PrimitiveArray label="Result" values={result} />;
    if (result.every(isRecord)) return <ObjectArrayTable label="Result" values={result} />;
    return <p className="text-sm text-text-muted">Result contains mixed list data. Use raw JSON for exact values.</p>;
  }

  if (!isRecord(result)) return <p className="text-sm text-text-muted">Result is not displayable. Use raw JSON for exact values.</p>;

  const entries = Object.entries(result);
  const primaryEntries = entries.filter(([key, value]) => PRIMARY_FIELD_NAMES.has(key) && isPrimitive(value));
  const fieldEntries = entries.filter(([key, value]) => !PRIMARY_FIELD_NAMES.has(key) && isPrimitive(value));
  const structuredEntries = entries.filter(([, value]) => isRecord(value) || Array.isArray(value));

  return (
    <div className="space-y-3">
      {primaryEntries.length > 0 && (
        <div className="grid gap-2">
          {primaryEntries.map(([key, value]) => <PrimitivePill key={key} label={key} value={value as JsonPrimitive} prominent />)}
        </div>
      )}

      {fieldEntries.length > 0 && (
        <section className="rounded-xl bg-bg-surface p-3 ring-1 ring-white/5">
          <p className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-text-muted">Fields</p>
          <KeyValueRows entries={fieldEntries} />
        </section>
      )}

      {structuredEntries.map(([key, value]) => {
        if (isRecord(value)) return <ObjectCard key={key} label={key} value={value} />;
        if (isPrimitiveArray(value)) return <PrimitiveArray key={key} label={key} values={value} />;
        if (Array.isArray(value) && value.every(isRecord)) return <ObjectArrayTable key={key} label={key} values={value} />;
        return (
          <section key={key} className="rounded-xl bg-bg-surface p-3 text-sm text-text-muted ring-1 ring-white/5">
            <span className="font-medium text-text-secondary">{humanizeKey(key)}:</span> Complex list data. Use raw JSON for exact values.
          </section>
        );
      })}

      {entries.length === 0 && <p className="text-sm text-text-muted">Result returned an empty object.</p>}
    </div>
  );
}

export function ResultRenderer({
  execution,
  compact = false,
  className,
}: {
  execution: Pick<Execution, "result" | "error_message" | "status"> | null | undefined;
  compact?: boolean;
  className?: string;
}) {
  const isFailure = execution?.status === "FAILED" || execution?.status === "TIMED_OUT" || execution?.status === "CANCELLED";
  const [rawOpen, setRawOpen] = useState(false);

  useEffect(() => {
    setRawOpen(false);
  }, [execution?.result]);

  if (!execution) {
    return <p className="text-sm text-text-muted">No execution selected.</p>;
  }

  return (
    <div className={cn("space-y-3", compact && "text-sm", className)}>
      {execution.result != null ? (
        <StructuredResult result={execution.result} />
      ) : execution.error_message ? (
        <div className="rounded-xl bg-error/10 p-4 text-error">
          <p className="text-sm font-medium">Execution error</p>
          <p className="mt-1 whitespace-pre-wrap font-mono text-xs text-error/85">{execution.error_message}</p>
        </div>
      ) : isFailure ? (
        <p className="text-sm text-error">Execution finished without a result.</p>
      ) : (
        <p className="text-sm text-text-muted">No result returned yet.</p>
      )}

      {execution.result != null && (
        <details
          open={rawOpen}
          onToggle={(event) => setRawOpen(event.currentTarget.open)}
          className="group rounded-xl bg-bg-raised/35 px-4 py-3 ring-1 ring-white/5"
        >
          <summary className="flex cursor-pointer list-none items-center justify-between text-xs font-medium text-text-muted transition-colors hover:text-text-primary">
            View raw JSON
            <ChevronDown size={14} className="transition-transform group-open:rotate-180" />
          </summary>
          {rawOpen && (
            <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-bg-base p-3 font-mono text-xs leading-5 text-text-primary">
              {JSON.stringify(execution.result, null, 2)}
            </pre>
          )}
        </details>
      )}
    </div>
  );
}