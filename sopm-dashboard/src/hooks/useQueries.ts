"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getDashboard,
  getDetailedHealth,
  getExecutionMetrics,
  getWorkerMetrics,
  getQueueMetrics,
  getFunctions,
  getFunction,
  createFunction,
  uploadFunctionVersion,
  getFunctionVersions,
  activateFunctionVersion,
  updateFunctionCanary,
  getExecutions,
  getExecution,
  getExecutionLogs,
  getSchedules,
  createSchedule,
  updateSchedule,
  deleteSchedule,
  deleteFunction,
  executeFunction,
  getApiKeys,
  createApiKey,
  revokeApiKey,
} from "@/lib/api";

// ─── Query Keys ────────────────────────────────────────────────────────────

export const QK = {
  dashboard: ["dashboard"] as const,
  health: ["health"] as const,
  metricsExecutions: ["metrics", "executions"] as const,
  metricsWorkers: ["metrics", "workers"] as const,
  metricsQueue: ["metrics", "queue"] as const,
  functions: (params?: object) => ["functions", params] as const,
  function: (id: string) => ["function", id] as const,
  functionVersions: (id: string) => ["function", id, "versions"] as const,
  executions: (params?: object) => ["executions", params] as const,
  execution: (id: string) => ["execution", id] as const,
  executionLogs: (id: string) => ["execution-logs", id] as const,
  schedules: (params?: object) => ["schedules", params] as const,
  apiKeys: ["api-keys"] as const,
};

// ─── Dashboard ─────────────────────────────────────────────────────────────

export function useDashboard() {
  return useQuery({
    queryKey: QK.dashboard,
    queryFn: getDashboard,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

export function useDetailedHealth() {
  return useQuery({
    queryKey: QK.health,
    queryFn: getDetailedHealth,
    refetchInterval: 15_000,
    staleTime: 10_000,
  });
}

// ─── Metrics ───────────────────────────────────────────────────────────────

export function useExecutionMetrics() {
  return useQuery({
    queryKey: QK.metricsExecutions,
    queryFn: getExecutionMetrics,
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useWorkerMetrics() {
  return useQuery({
    queryKey: QK.metricsWorkers,
    queryFn: getWorkerMetrics,
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}

export function useQueueMetrics() {
  return useQuery({
    queryKey: QK.metricsQueue,
    queryFn: getQueueMetrics,
    refetchInterval: 5_000,
    staleTime: 3_000,
  });
}

// ─── Functions ─────────────────────────────────────────────────────────────

export function useFunctions(params?: { page?: number; size?: number; search?: string; status?: string }) {
  return useQuery({
    queryKey: QK.functions(params),
    queryFn: () => getFunctions(params),
    staleTime: 30_000,
  });
}

export function useFunctionDetail(id: string) {
  return useQuery({
    queryKey: QK.function(id),
    queryFn: () => getFunction(id),
    enabled: !!id,
  });
}


export function useFunctionVersions(id: string) {
  return useQuery({
    queryKey: QK.functionVersions(id),
    queryFn: () => getFunctionVersions(id),
    enabled: !!id,
  });
}

export function useActivateFunctionVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: activateFunctionVersion,
    onSuccess: (_fn, input) => {
      qc.invalidateQueries({ queryKey: ["functions"] });
      qc.invalidateQueries({ queryKey: QK.function(input.functionId) });
      qc.invalidateQueries({ queryKey: QK.functionVersions(input.functionId) });
    },
  });
}

export function useUpdateFunctionCanary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: updateFunctionCanary,
    onSuccess: (_fn, input) => {
      qc.invalidateQueries({ queryKey: ["functions"] });
      qc.invalidateQueries({ queryKey: QK.function(input.functionId) });
      qc.invalidateQueries({ queryKey: QK.functionVersions(input.functionId) });
    },
  });
}
export function useDeleteFunction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteFunction,
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: QK.function(id) });
      qc.removeQueries({ queryKey: QK.functionVersions(id) });
      qc.invalidateQueries({ queryKey: ["functions"] });
      qc.invalidateQueries({ queryKey: ["executions"] });
      qc.invalidateQueries({ queryKey: ["schedules"] });
      qc.invalidateQueries({ queryKey: QK.dashboard });
    },
  });
}

export function useCreateFunction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createFunction,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["functions"] }),
  });
}

export function useUploadFunctionVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: uploadFunctionVersion,
    onSuccess: (_version, input) => {
      qc.invalidateQueries({ queryKey: ["functions"] });
      qc.invalidateQueries({ queryKey: QK.function(input.id) });
      qc.invalidateQueries({ queryKey: QK.dashboard });
    },
  });
}

export function useExecuteFunction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload?: Record<string, unknown> }) =>
      executeFunction(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["executions"] }),
  });
}

// ─── Executions ────────────────────────────────────────────────────────────

export function useExecutions(params?: {
  page?: number;
  size?: number;
  function_id?: string;
  status?: string;
  failure_kind?: string;
  source?: string;
}) {
  return useQuery({
    queryKey: QK.executions(params),
    queryFn: () => getExecutions(params),
    refetchInterval: 10_000,
    staleTime: 5_000,
  });
}

export function useExecutionDetail(id: string) {
  return useQuery({
    queryKey: QK.execution(id),
    queryFn: () => getExecution(id),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "RUNNING" || status === "PENDING" || status === "QUEUED") return 250;
      return false;
    },
  });
}

export function useExecutionLogs(id: string, status?: string | null) {
  const isLive = status === "RUNNING" || status === "PENDING" || status === "QUEUED";

  return useQuery({
    queryKey: QK.executionLogs(id),
    queryFn: () => getExecutionLogs(id),
    enabled: !!id,
    refetchInterval: isLive ? 3_000 : false,
    staleTime: isLive ? 1_000 : 60_000,
  });
}

// Schedules

export function useSchedules(params?: { page?: number; size?: number }) {
  return useQuery({
    queryKey: QK.schedules(params),
    queryFn: () => getSchedules(params),
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}

export function useCreateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
}

export function useUpdateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: updateSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
}

export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: deleteSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
}
// API Keys

export function useApiKeys() {
  return useQuery({
    queryKey: QK.apiKeys,
    queryFn: getApiKeys,
    staleTime: 15_000,
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: createApiKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.apiKeys }),
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: revokeApiKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.apiKeys }),
  });
}



