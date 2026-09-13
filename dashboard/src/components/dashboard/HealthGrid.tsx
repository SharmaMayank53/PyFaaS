"use client";

import { HealthDot, Card } from "@/components/ui";
import { healthColor } from "@/lib/utils";
import type { HealthComponents, HealthStatus } from "@/types";
import { Spinner } from "@/components/ui";

const COMPONENT_LABELS: Record<keyof HealthComponents, string> = {
  api: "API Gateway",
  postgres: "PostgreSQL",
  redis: "Redis",
  minio: "MinIO",
  kubernetes: "Kubernetes",
  runner_pool: "Runner Pool",
};

interface HealthGridProps {
  health: HealthComponents | null;
  loading?: boolean;
}

export function HealthGrid({ health, loading }: HealthGridProps) {
  return (
    <div>
      <p className="text-xs font-medium text-text-secondary uppercase tracking-wider mb-3">
        System Health
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {(Object.keys(COMPONENT_LABELS) as Array<keyof HealthComponents>).map((key) => {
          const status: HealthStatus = health?.[key] ?? "unhealthy";
          const label = COMPONENT_LABELS[key];
          return (
            <Card key={key} className="flex items-center gap-3 py-3 px-4">
              {loading ? (
                <Spinner className="w-3.5 h-3.5 shrink-0" />
              ) : (
                <HealthDot status={status} />
              )}
              <div className="min-w-0">
                <p className="text-xs font-medium text-text-primary truncate">{label}</p>
                <p className={`text-xs font-mono ${healthColor(status)}`}>{status}</p>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}


