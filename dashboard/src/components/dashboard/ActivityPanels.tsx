"use client";

import { Table, Thead, Th, Tbody, Tr, Td, StatusBadge, EmptyState, Card } from "@/components/ui";
import { formatRelative, formatDuration, truncate } from "@/lib/utils";
import type { Execution, Deployment } from "@/types";
import Link from "next/link";

// ─── Recent Executions ─────────────────────────────────────────────────────

export function RecentExecutions({ executions }: { executions: Execution[] }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-medium text-text-secondary uppercase tracking-wider">
          Recent Executions
        </p>
        <Link href="/executions" className="text-xs text-accent hover:underline">
          View all
        </Link>
      </div>
      <Card noPad>
        {executions.length === 0 ? (
          <EmptyState message="No executions yet" />
        ) : (
          <Table>
            <Thead>
              <tr>
                <Th>Function</Th>
                <Th>Status</Th>
                <Th>Duration</Th>
                <Th>When</Th>
              </tr>
            </Thead>
            <Tbody>
              {executions.map((ex) => (
                <Tr key={ex.id}>
                  <Td>
                    <Link
                      href={`/executions/${ex.id}`}
                      className="font-mono text-xs text-accent hover:underline"
                    >
                      {ex.function_name ?? truncate(ex.id, 12)}
                    </Link>
                  </Td>
                  <Td>
                    <StatusBadge status={ex.status} />
                  </Td>
                  <Td>
                    <span className="font-mono text-xs text-text-secondary">
                      {formatDuration(ex.duration_ms)}
                    </span>
                  </Td>
                  <Td>
                    <span className="text-xs text-text-secondary">
                      {formatRelative(ex.created_at)}
                    </span>
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

// ─── Recent Failures ───────────────────────────────────────────────────────

export function RecentFailures({ failures }: { failures: Execution[] }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-medium text-text-secondary uppercase tracking-wider">
          Recent Failures
        </p>
        <Link href="/executions?status=FAILED" className="text-xs text-error hover:underline">
          View all
        </Link>
      </div>
      <Card noPad>
        {failures.length === 0 ? (
          <EmptyState message="No failures — nice." />
        ) : (
          <Table>
            <Thead>
              <tr>
                <Th>Function</Th>
                <Th>Error</Th>
                <Th>When</Th>
              </tr>
            </Thead>
            <Tbody>
              {failures.map((ex) => (
                <Tr key={ex.id}>
                  <Td>
                    <Link
                      href={`/executions/${ex.id}`}
                      className="font-mono text-xs text-accent hover:underline"
                    >
                      {ex.function_name ?? truncate(ex.id, 12)}
                    </Link>
                  </Td>
                  <Td>
                    <span className="text-xs text-error font-mono truncate max-w-[200px] block">
                      {ex.error_message ? truncate(ex.error_message, 60) : ex.status}
                    </span>
                  </Td>
                  <Td>
                    <span className="text-xs text-text-secondary">
                      {formatRelative(ex.created_at)}
                    </span>
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

// ─── Recent Deployments ────────────────────────────────────────────────────

export function RecentDeployments({ deployments }: { deployments: Deployment[] }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-medium text-text-secondary uppercase tracking-wider">
          Recent Deployments
        </p>
        <Link href="/functions" className="text-xs text-accent hover:underline">
          View all
        </Link>
      </div>
      <Card noPad>
        {deployments.length === 0 ? (
          <EmptyState message="No deployments yet" />
        ) : (
          <Table>
            <Thead>
              <tr>
                <Th>Function</Th>
                <Th>Version</Th>
                <Th>Runtime</Th>
                <Th>When</Th>
              </tr>
            </Thead>
            <Tbody>
              {deployments.map((d) => (
                <Tr key={d.id}>
                  <Td>
                    <Link
                      href={`/functions/${d.function_id}`}
                      className="font-mono text-xs text-accent hover:underline"
                    >
                      {d.function_name ?? truncate(d.function_id, 12)}
                    </Link>
                  </Td>
                  <Td>
                    <span className="font-mono text-xs text-text-secondary">v{d.version_number}</span>
                  </Td>
                  <Td>
                    <span className="font-mono text-xs text-text-secondary">{d.runtime ?? "—"}</span>
                  </Td>
                  <Td>
                    <span className="text-xs text-text-secondary">
                      {formatRelative(d.created_at)}
                    </span>
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


