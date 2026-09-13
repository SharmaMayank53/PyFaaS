// â”€â”€â”€ Health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export type HealthStatus = "healthy" | "degraded" | "unhealthy";

export interface HealthComponents {
  api: HealthStatus;
  postgres: HealthStatus;
  redis: HealthStatus;
  minio: HealthStatus;
  kubernetes: HealthStatus;
  runner_pool: HealthStatus;
}

export interface DetailedHealth {
  overall: HealthStatus;
  components: HealthComponents;
  timestamp: string;
}

// â”€â”€â”€ Overview â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export interface Overview {
  active_functions: number;
  running_executions: number;
  successful_executions_24h: number;
  failed_executions_24h: number;
  queue_depth: number;
  active_workers: number;
}

// â”€â”€â”€ Executions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export type ExecutionStatus =
  | "PENDING"
  | "QUEUED"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "TIMED_OUT"
  | "CANCELLED";

export interface Execution {
  id: string;
  function_id: string | null;
  function_name: string | null;
  execution_type: "function" | "ephemeral" | string;
  status: ExecutionStatus;
  payload?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  duration_ms: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  worker_id: string | null;
  error_message: string | null;
  failure_kind: string | null;
  function_version_id?: string | null;
}

export interface ExecutionMetrics {
  total_24h: number;
  completed_24h: number;
  failed_24h: number;
  success_rate: number;
  avg_runtime_ms: number;
  p95_runtime_ms: number;
  p99_runtime_ms: number;
  hourly_trend: HourlyTrend[];
}

export interface HourlyTrend {
  hour: string;
  total: number;
  completed: number;
  failed: number;
}

// â”€â”€â”€ Deployments â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export interface Deployment {
  id: string;
  function_id: string;
  function_name: string | null;
  version_number: number;
  runtime: string | null;
  artifact_size: number | null;
  is_active: boolean;
  created_at: string;
}

// â”€â”€â”€ Workers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export interface WorkerInfo {
  worker_id: string;
  last_heartbeat: string | null;
  age_seconds: number;
  status: "online" | "stale";
}

export interface WorkerMetrics {
  workers: WorkerInfo[];
  total: number;
  online: number;
}

// â”€â”€â”€ Queue â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export interface QueueMetrics {
  queue_depth: number;
  processing_depth: number;
  dlq_depth: number;
}

// â”€â”€â”€ Dashboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export interface DashboardMetrics {
  success_rate: number;
  avg_runtime: number;
  executions_last_24h: HourlyTrend[];
  total_24h: number;
  p95_runtime_ms: number;
  p99_runtime_ms: number;
}

export interface DashboardData {
  overview: Overview;
  health: HealthComponents;
  deployments: Deployment[];
  recent_executions: Execution[];
  recent_failures: Execution[];
  metrics: DashboardMetrics;
  timestamp: string;
}

// â”€â”€â”€ Functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export type FunctionStatus = "ACTIVE" | "INACTIVE" | "DEPRECATED";

export interface FunctionVersion {
  id: string;
  version_number: number;
  entrypoint: string;
  artifact_size: number;
  timeout: number;
  memory_mb: number;
  is_active: boolean;
  created_at: string;
  change_notes: string | null;
}

export interface FunctionRecord {
  id: string;
  name: string;
  description: string | null;
  runtime: string;
  status: FunctionStatus;
  tags: Record<string, string>;
  created_at: string;
  updated_at: string;
  active_version_id?: string | null;
  canary_version_id?: string | null;
  canary_percent: number;
  active_version?: FunctionVersion | null;
  canary_version?: FunctionVersion | null;
}

export interface PaginatedFunctions {
  items: FunctionRecord[];
  total: number;
  page: number;
  size: number;
}
export type ScheduleStatus = "ACTIVE" | "PAUSED" | "DELETED";

export interface Schedule {
  id: string;
  function_id: string;
  name: string;
  cron_expression: string;
  payload: Record<string, unknown>;
  status: ScheduleStatus;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleListResponse {
  items: Schedule[];
  total: number;
}

// â”€â”€â”€ WebSocket Events â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export type WsEventType =
  | "execution_started"
  | "execution_completed"
  | "execution_failed"
  | "deployment_started"
  | "deployment_completed"
  | "worker_online"
  | "worker_offline"
  | "queue_depth_changed"
  | "health_changed"
  | "keepalive"
  | "pong";

export interface WsEvent<T = Record<string, unknown>> {
  type: WsEventType;
  payload: T;
  timestamp: string;
}




