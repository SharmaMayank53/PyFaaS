import axios, { type AxiosInstance } from "axios";
import type {
  DashboardData,
  DetailedHealth,
  ExecutionMetrics,
  FunctionRecord,
  FunctionVersion,
  PaginatedFunctions,
  QueueMetrics,
  Schedule,
  ScheduleListResponse,
  WorkerMetrics,
  Execution,
} from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function createClient(): AxiosInstance {
  const client = axios.create({
    baseURL: `${BASE_URL}/api/v1`,
    timeout: 10_000,
    headers: { "Content-Type": "application/json" },
  });

  // Attach JWT from localStorage on every request
  client.interceptors.request.use((config) => {
    if (typeof FormData !== "undefined" && config.data instanceof FormData) {
      delete config.headers["Content-Type"];
    }
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("sopm_token");
      if (token) config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  // Global 401 â†’ redirect to login
  client.interceptors.response.use(
    (r) => r,
    (err) => {
      if (err.response?.status === 401 && typeof window !== "undefined") {
        localStorage.removeItem("sopm_token");
        localStorage.removeItem("sopm-auth");
        document.cookie = "sopm_token=; path=/; max-age=0; SameSite=Lax";
        window.location.href = "/login";
      }
      return Promise.reject(err);
    }
  );

  return client;
}

export const api = createClient();

// â”€â”€â”€ Auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export async function registerUser(input: { username: string; email: string; password: string }): Promise<{ id: string; username: string; email: string }> {
  const res = await api.post<{ id: string; username: string; email: string }>("/auth/register", input);
  return res.data;
}

export async function login(username: string, password: string): Promise<{ access_token: string }> {
  const params = new URLSearchParams({ username, password });
  const res = await api.post<{ access_token: string }>("/auth/login", params, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return res.data;
}

export async function getCurrentUser(): Promise<{ username: string }> {
  const res = await api.get<{ username: string }>("/auth/me");
  return res.data;
}

// â”€â”€â”€ Dashboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export async function getDashboard(): Promise<DashboardData> {
  const res = await api.get<DashboardData>("/dashboard");
  return res.data;
}

export async function getDetailedHealth(): Promise<DetailedHealth> {
  const res = await api.get<DetailedHealth>("/health/detailed");
  return res.data;
}

// â”€â”€â”€ Metrics â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export async function getExecutionMetrics(): Promise<ExecutionMetrics> {
  const res = await api.get<ExecutionMetrics>("/metrics/executions");
  return res.data;
}

export async function getWorkerMetrics(): Promise<WorkerMetrics> {
  const res = await api.get<WorkerMetrics>("/metrics/workers");
  return res.data;
}

export async function getQueueMetrics(): Promise<QueueMetrics> {
  const res = await api.get<QueueMetrics>("/metrics/queue");
  return res.data;
}

// â”€â”€â”€ Functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export async function getFunctions(params?: {
  page?: number;
  size?: number;
  search?: string;
  status?: string;
  failure_kind?: string;
}): Promise<PaginatedFunctions> {
  const res = await api.get<PaginatedFunctions>("/functions", { params });
  return res.data;
}

export async function createFunction(body: {
  name: string;
  description?: string;
  tags?: Record<string, string>;
}): Promise<FunctionRecord> {
  const res = await api.post<FunctionRecord>("/functions", {
    name: body.name,
    description: body.description || null,
    tags: body.tags ?? {},
  });
  return res.data;
}

export async function getFunction(id: string): Promise<FunctionRecord> {
  const res = await api.get<FunctionRecord>(`/functions/${id}`);
  return res.data;
}

export async function uploadFunctionVersion(input: {
  id: string;
  archive: File;
  entrypoint: string;
  timeout: number;
  memory_mb: number;
  change_notes?: string;
}): Promise<FunctionVersion> {
  const data = new FormData();
  data.append("archive", input.archive);
  data.append("entrypoint", input.entrypoint);
  data.append("timeout", String(input.timeout));
  data.append("memory_mb", String(input.memory_mb));
  if (input.change_notes) data.append("change_notes", input.change_notes);

  const res = await api.post<FunctionVersion>(`/functions/${input.id}/versions`, data);
  return res.data;
}


export async function getFunctionVersions(id: string): Promise<{ items: FunctionVersion[]; total: number }> {
  const res = await api.get<{ items: FunctionVersion[]; total: number }>(`/functions/${id}/versions`);
  return res.data;
}

export async function activateFunctionVersion(input: { functionId: string; versionId: string }): Promise<FunctionRecord> {
  const res = await api.post<FunctionRecord>(`/functions/${input.functionId}/versions/${input.versionId}/activate`);
  return res.data;
}

export async function updateFunctionCanary(input: {
  functionId: string;
  canary_version_id: string | null;
  canary_percent: number;
}): Promise<FunctionRecord> {
  const res = await api.patch<FunctionRecord>(`/functions/${input.functionId}/canary`, {
    canary_version_id: input.canary_version_id,
    canary_percent: input.canary_percent,
  });
  return res.data;
}
export async function deleteFunction(id: string): Promise<void> {
  await api.delete(`/functions/${id}`);
}

export async function executeFunction(
  id: string,
  payload?: Record<string, unknown>
): Promise<Execution> {
  const res = await api.post<Execution>(`/functions/${id}/execute`, { payload: payload ?? {} });
  return res.data;
}

// â”€â”€â”€ Executions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export async function getExecutions(params?: {
  page?: number;
  size?: number;
  function_id?: string;
  status?: string;
  failure_kind?: string;
  source?: string;
}): Promise<{ items: Execution[]; total: number }> {
  const res = await api.get<{ items: Execution[]; total: number }>("/executions", { params });
  return res.data;
}

export async function getExecution(id: string): Promise<Execution> {
  const res = await api.get<Execution>(`/executions/${id}`);
  return res.data;
}

export async function getExecutionLogs(
  id: string
): Promise<Array<{ timestamp: string; level: string; stream: string; message: string }>> {
  const res = await api.get<{
    logs: Array<{ timestamp: string; level: string; stream: string; message: string }>;
  }>(`/executions/${id}/logs`);
  return res.data.logs;
}

// Schedules

export async function getSchedules(params?: {
  page?: number;
  size?: number;
}): Promise<ScheduleListResponse> {
  const res = await api.get<ScheduleListResponse>("/schedules", { params });
  return res.data;
}

export async function createSchedule(input: {
  function_id: string;
  name: string;
  cron_expression: string;
  payload: Record<string, unknown>;
}): Promise<Schedule> {
  const res = await api.post<Schedule>(
    "/schedules",
    {
      name: input.name,
      cron_expression: input.cron_expression,
      payload: input.payload,
    },
    { params: { function_id: input.function_id } }
  );
  return res.data;
}

export async function updateSchedule(input: {
  id: string;
  status?: "ACTIVE" | "PAUSED" | "DELETED";
  name?: string;
  cron_expression?: string;
  payload?: Record<string, unknown>;
}): Promise<Schedule> {
  const { id, ...body } = input;
  const res = await api.patch<Schedule>(`/schedules/${id}`, body);
  return res.data;
}

export async function deleteSchedule(id: string): Promise<void> {
  await api.delete(`/schedules/${id}`);
}
export interface ApiKeyRecord {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreateResponse extends ApiKeyRecord {
  key: string;
}

export async function getApiKeys(): Promise<ApiKeyRecord[]> {
  const res = await api.get<ApiKeyRecord[]>("/keys");
  return res.data;
}

export async function createApiKey(name: string): Promise<ApiKeyCreateResponse> {
  const res = await api.post<ApiKeyCreateResponse>("/keys", { name });
  return res.data;
}

export async function revokeApiKey(id: string): Promise<void> {
  await api.delete(`/keys/${id}`);
}



