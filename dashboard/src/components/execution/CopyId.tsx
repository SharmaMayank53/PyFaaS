"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui";
import { truncate } from "@/lib/utils";

export function CopyId({ value, label = "Copy ID", short = 12 }: { value: string | null | undefined; label?: string; short?: number }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="text-text-muted">-</span>;

  async function copy() {
    await navigator.clipboard.writeText(value as string);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg bg-bg-raised px-2 py-1 font-mono text-xs text-text-secondary">
      {truncate(value, short)}
      <Button type="button" variant="ghost" size="sm" className="h-5 px-1 py-0" onClick={copy} title={label}>
        {copied ? <Check size={11} className="text-success" /> : <Copy size={11} />}
      </Button>
    </span>
  );
}


