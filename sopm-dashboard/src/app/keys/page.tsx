"use client";

import { useState } from "react";
import { Button, Card, EmptyState, Input, Spinner, Table, Tbody, Td, Th, Thead, Tr, Badge } from "@/components/ui";
import { useApiKeys, useCreateApiKey, useRevokeApiKey } from "@/hooks/useQueries";
import { CopyId } from "@/components/execution/CopyId";
import { formatRelative } from "@/lib/utils";
import { KeyRound, RefreshCw, Trash2 } from "lucide-react";

export default function ApiKeysPage() {
  const [name, setName] = useState("default");
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const { data, isLoading, refetch, isFetching } = useApiKeys();
  const createMut = useCreateApiKey();
  const revokeMut = useRevokeApiKey();

  async function handleCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const key = await createMut.mutateAsync(name.trim() || "default");
    setCreatedKey(key.key);
    setName("default");
  }

  async function handleRevoke(id: string, label: string) {
    if (!confirm(`Revoke API key "${label}"? Existing clients using it will stop working.`)) return;
    await revokeMut.mutateAsync(id);
  }

  const keys = data ?? [];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">API Keys</h1>
          <p className="mt-1 text-sm text-text-muted">External invoke access for CLI and HTTP clients.</p>
        </div>
        <button onClick={() => refetch()} className="text-text-muted hover:text-text-primary" title="Refresh keys">
          <RefreshCw size={15} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      <Card elevated>
        <form onSubmit={handleCreate} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label className="mb-1.5 block text-xs text-text-muted">Key name</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="ci-deploy" />
          </div>
          <Button type="submit" variant="primary" loading={createMut.isPending}>
            <KeyRound size={14} />
            Generate key
          </Button>
        </form>
        {createdKey && (
          <div className="mt-4 rounded-xl bg-warning/10 p-3 text-sm text-warning ring-1 ring-warning/20">
            <p className="font-medium">Copy this key now. It will not be shown again.</p>
            <div className="mt-2"><CopyId value={createdKey} short={64} label="Copy API key" /></div>
          </div>
        )}
      </Card>

      <Card noPad>
        {isLoading ? <div className="flex justify-center py-16"><Spinner /></div> : !keys.length ? <EmptyState message="No API keys yet" /> : (
          <Table>
            <Thead><tr><Th>Name</Th><Th>Prefix</Th><Th>Created</Th><Th>Last used</Th><Th>Status</Th><Th></Th></tr></Thead>
            <Tbody>
              {keys.map((key) => (
                <Tr key={key.id}>
                  <Td><span className="font-medium text-text-primary">{key.name}</span></Td>
                  <Td><span className="font-mono text-xs text-text-muted">{key.key_prefix}</span></Td>
                  <Td><span className="text-xs text-text-muted">{formatRelative(key.created_at)}</span></Td>
                  <Td><span className="text-xs text-text-muted">{formatRelative(key.last_used_at)}</span></Td>
                  <Td><Badge variant={key.revoked_at ? "error" : "success"}>{key.revoked_at ? "revoked" : "active"}</Badge></Td>
                  <Td>
                    {!key.revoked_at && (
                      <Button size="sm" variant="ghost" loading={revokeMut.isPending} onClick={() => handleRevoke(key.id, key.name)} title="Revoke key">
                        <Trash2 size={12} className="text-error" />
                      </Button>
                    )}
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
