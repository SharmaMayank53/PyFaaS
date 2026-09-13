"use client";

import * as React from "react";
import { Loader2 } from "lucide-react";
import { cn, healthDot, statusBg } from "@/lib/utils";
import type { ExecutionStatus, HealthStatus } from "@/types";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  noPad?: boolean;
  elevated?: boolean;
}

export function Card({ className, children, noPad, elevated, ...props }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl bg-bg-surface shadow-card ring-1 ring-white/5",
        elevated && "bg-bg-raised shadow-panel",
        !noPad && "p-4",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mb-4 flex items-center justify-between", className)} {...props}>{children}</div>;
}

export function CardTitle({ className, children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-xs font-semibold uppercase tracking-wider text-text-muted", className)} {...props}>{children}</h3>;
}

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "success" | "warning" | "error" | "info";
}

const badgeVariants: Record<NonNullable<BadgeProps["variant"]>, string> = {
  default: "bg-bg-raised text-text-secondary ring-white/10",
  success: "bg-success/12 text-success ring-success/20",
  warning: "bg-warning/12 text-warning ring-warning/20",
  error: "bg-error/12 text-error ring-error/20",
  info: "bg-accent/12 text-accent ring-accent/20",
};

export function Badge({ className, variant = "default", children, ...props }: BadgeProps) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1", badgeVariants[variant], className)} {...props}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: ExecutionStatus }) {
  return <span className={cn("inline-flex items-center rounded-full px-2.5 py-1 text-xs font-mono font-medium ring-1", statusBg(status))}>{status}</span>;
}

export function HealthDot({ status }: { status: HealthStatus }) {
  const isPulse = status === "healthy";
  return (
    <span className="relative inline-flex h-2.5 w-2.5">
      {isPulse && <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-60", healthDot(status))} />}
      <span className={cn("relative inline-flex h-2.5 w-2.5 rounded-full", healthDot(status))} />
    </span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("animate-spin text-text-muted", className)} size={16} />;
}

export function Table({ className, children, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  return <div className="w-full overflow-x-auto"><table className={cn("w-full text-sm", className)} {...props}>{children}</table></div>;
}

export function Thead({ className, children, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("border-b border-white/10", className)} {...props}>{children}</thead>;
}

export function Th({ className, children, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-text-muted", className)} {...props}>{children}</th>;
}

export function Tbody({ className, children, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("divide-y divide-white/10", className)} {...props}>{children}</tbody>;
}

export function Tr({ className, children, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn("transition-colors hover:bg-white/[0.025]", className)} {...props}>{children}</tr>;
}

export function Td({ className, children, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("px-4 py-3 text-text-primary", className)} {...props}>{children}</td>;
}

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "ghost" | "danger" | "outline";
  size?: "sm" | "md";
  loading?: boolean;
}

const buttonVariants: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary: "bg-accent text-bg-base shadow-[0_10px_30px_rgba(56,189,248,0.20)] hover:bg-accent-hover",
  ghost: "text-text-muted hover:bg-white/10 hover:text-text-primary",
  danger: "bg-error/10 text-error ring-1 ring-error/25 hover:bg-error/15",
  outline: "bg-bg-raised text-text-primary ring-1 ring-white/10 hover:bg-white/10",
};

const buttonSizes: Record<NonNullable<ButtonProps["size"]>, string> = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
};

export function Button({ className, variant = "outline", size = "md", loading, disabled, children, ...props }: ButtonProps) {
  return (
    <button
      className={cn("inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all disabled:cursor-not-allowed disabled:opacity-50", buttonVariants[variant], buttonSizes[size], className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading && <Spinner className="h-3.5 w-3.5" />}
      {children}
    </button>
  );
}

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn("w-full rounded-lg bg-bg-raised px-3 py-2 text-sm text-text-primary ring-1 ring-white/10 transition-colors placeholder:text-text-faint focus:outline-none focus:ring-accent/100", className)}
      {...props}
    />
  );
}

export function EmptyState({ message = "No data available" }: { message?: string }) {
  return <div className="flex flex-col items-center justify-center py-12 text-text-muted"><p className="text-sm">{message}</p></div>;
}

interface MetricCardProps {
  label: string;
  value: string | number;
  sub?: string;
  trend?: "up" | "down" | "neutral";
  loading?: boolean;
  accent?: string;
}

export function MetricCard({ label, value, sub, loading, accent }: MetricCardProps) {
  return (
    <div className="rounded-2xl bg-bg-surface p-4 shadow-card ring-1 ring-white/5">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">{label}</p>
      {loading ? <div className="mt-3 h-8 w-24 animate-pulse rounded-lg bg-white/10" /> : <p className={cn("mt-2 font-mono text-2xl font-bold text-text-primary", accent)}>{value}</p>}
      {sub && <p className="mt-1 text-xs text-text-muted">{sub}</p>}
    </div>
  );
}

export function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return <div className="mb-3 flex items-center justify-between"><h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted">{title}</h2>{action}</div>;
}


