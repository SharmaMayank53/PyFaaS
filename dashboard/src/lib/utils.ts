import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { ExecutionStatus, HealthStatus } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function statusColor(status: ExecutionStatus): string {
  switch (status) {
    case "COMPLETED":
      return "text-success";
    case "RUNNING":
      return "text-accent";
    case "PENDING":
    case "QUEUED":
      return "text-warning";
    case "FAILED":
    case "TIMED_OUT":
      return "text-error";
    case "CANCELLED":
      return "text-text-secondary";
    default:
      return "text-text-secondary";
  }
}

export function statusBg(status: ExecutionStatus): string {
  switch (status) {
    case "COMPLETED":
      return "bg-success/12 text-success ring-success/20";
    case "RUNNING":
      return "bg-accent/12 text-accent ring-accent/20";
    case "PENDING":
    case "QUEUED":
      return "bg-warning/12 text-warning ring-warning/20";
    case "FAILED":
    case "TIMED_OUT":
      return "bg-error/12 text-error ring-error/20";
    case "CANCELLED":
      return "bg-bg-raised text-text-secondary ring-white/10";
    default:
      return "bg-bg-raised text-text-secondary ring-white/10";
  }
}

export function healthColor(status: HealthStatus): string {
  switch (status) {
    case "healthy":
      return "text-success";
    case "degraded":
      return "text-warning";
    case "unhealthy":
      return "text-error";
  }
}

export function healthDot(status: HealthStatus): string {
  switch (status) {
    case "healthy":
      return "bg-success";
    case "degraded":
      return "bg-warning";
    case "unhealthy":
      return "bg-error";
  }
}

export function truncate(str: string, n: number): string {
  return str.length > n ? str.slice(0, n) + "…" : str;
}



