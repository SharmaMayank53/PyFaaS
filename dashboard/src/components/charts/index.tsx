"use client";

import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { format, parseISO } from "date-fns";
import type { HourlyTrend } from "@/types";
import { Spinner } from "@/components/ui";

// ─── Shared Tooltip ────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded border border-border bg-bg-panel px-3 py-2 text-xs shadow-xl">
      <p className="text-text-secondary mb-1 font-mono">{label}</p>
      {payload.map((p: any) => (
        <p key={p.name} style={{ color: p.color }} className="font-mono">
          {p.name}: <span className="font-bold">{p.value}</span>
        </p>
      ))}
    </div>
  );
}

function formatHour(iso: string) {
  try {
    return format(parseISO(iso), "HH:mm");
  } catch {
    return iso;
  }
}

function ChartContainer({
  title,
  children,
  loading,
  height = 160,
}: {
  title: string;
  children: React.ReactNode;
  loading?: boolean;
  height?: number;
}) {
  return (
    <div className="rounded-lg border border-border bg-bg-panel p-4">
      <p className="text-xs font-medium text-text-secondary uppercase tracking-wider mb-3">{title}</p>
      {loading ? (
        <div className="flex items-center justify-center" style={{ height }}>
          <Spinner />
        </div>
      ) : (
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            {children as React.ReactElement}
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// ─── Execution Trend Chart ─────────────────────────────────────────────────

export function ExecutionTrendChart({
  data,
  loading,
}: {
  data: HourlyTrend[];
  loading?: boolean;
}) {
  const chartData = data.map((d) => ({
    hour: formatHour(d.hour),
    Completed: d.completed,
    Failed: d.failed,
  }));

  return (
    <ChartContainer title="Execution Trend (24h)" loading={loading}>
      <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
        <defs>
          <linearGradient id="gradCompleted" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#3B82F6" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#3B82F6" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gradFailed" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#EF4444" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#EF4444" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
        <XAxis dataKey="hour" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip content={<ChartTooltip />} />
        <Area
          type="monotone"
          dataKey="Completed"
          stroke="#3B82F6"
          strokeWidth={1.5}
          fill="url(#gradCompleted)"
          dot={false}
        />
        <Area
          type="monotone"
          dataKey="Failed"
          stroke="#EF4444"
          strokeWidth={1.5}
          fill="url(#gradFailed)"
          dot={false}
        />
      </AreaChart>
    </ChartContainer>
  );
}

// ─── Success Rate Chart ────────────────────────────────────────────────────

export function SuccessRateChart({
  data,
  loading,
}: {
  data: HourlyTrend[];
  loading?: boolean;
}) {
  const chartData = data.map((d) => ({
    hour: formatHour(d.hour),
    Rate: d.total > 0 ? Math.round((d.completed / d.total) * 100) : 0,
  }));

  return (
    <ChartContainer title="Success Rate (24h)" loading={loading}>
      <LineChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
        <XAxis dataKey="hour" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
        <YAxis
          domain={[0, 100]}
          tick={{ fontSize: 10 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v) => `${v}%`}
        />
        <Tooltip content={<ChartTooltip />} formatter={(v) => [`${v}%`, "Rate"]} />
        <Line
          type="monotone"
          dataKey="Rate"
          stroke="#22C55E"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 3, fill: "#22C55E" }}
        />
      </LineChart>
    </ChartContainer>
  );
}

// ─── Queue Depth Chart ─────────────────────────────────────────────────────

export function QueueDepthChart({
  data,
  loading,
}: {
  data: Array<{ time: string; depth: number }>;
  loading?: boolean;
}) {
  return (
    <ChartContainer title="Queue Depth" loading={loading}>
      <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
        <defs>
          <linearGradient id="gradQueue" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#F59E0B" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#F59E0B" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" />
        <XAxis dataKey="time" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip content={<ChartTooltip />} />
        <Area
          type="monotone"
          dataKey="depth"
          stroke="#F59E0B"
          strokeWidth={1.5}
          fill="url(#gradQueue)"
          dot={false}
          name="Depth"
        />
      </AreaChart>
    </ChartContainer>
  );
}

// ─── Worker Utilization ────────────────────────────────────────────────────

export function WorkerUtilizationChart({
  online,
  total,
  loading,
}: {
  online: number;
  total: number;
  loading?: boolean;
}) {
  const data = [
    { name: "Online", value: online, fill: "#22C55E" },
    { name: "Stale", value: Math.max(0, total - online), fill: "#EF4444" },
  ];

  return (
    <ChartContainer title="Worker Utilization" loading={loading} height={160}>
      <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1F2937" vertical={false} />
        <XAxis dataKey="name" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip content={<ChartTooltip />} />
        <Bar dataKey="value" radius={[3, 3, 0, 0]} name="Workers">
          {data.map((entry, i) => (
            <rect key={i} fill={entry.fill} />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}


