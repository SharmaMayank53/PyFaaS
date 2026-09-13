"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Activity } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { registerUser } from "@/lib/api";

function messageFromError(err: any) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item?.msg ?? JSON.stringify(item)).join("; ");
  return err?.message ?? "Registration failed.";
}

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await registerUser({ username, email, password });
      router.push("/login?registered=1");
    } catch (err: any) {
      setError(messageFromError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg-base px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center justify-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent shadow-[0_12px_32px_rgba(56,189,248,0.22)]">
            <Activity size={17} className="text-bg-base" />
          </div>
          <span className="font-mono text-xl font-bold tracking-tight text-text-primary">SOPM</span>
        </div>

        <div className="rounded-2xl bg-bg-surface p-6 shadow-panel ring-1 ring-white/10">
          <h1 className="mb-1 text-lg font-semibold text-text-primary">Create account</h1>
          <p className="mb-6 text-sm text-text-muted">Start using the operations dashboard.</p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs text-text-muted">Username</label>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} required autoComplete="username" placeholder="admin" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-text-muted">Email</label>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" placeholder="admin@example.com" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs text-text-muted">Password</label>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" placeholder="At least 8 characters" />
            </div>

            {error && <p className="font-mono text-xs text-error">{error}</p>}

            <Button type="submit" variant="primary" loading={loading} className="w-full py-2.5">Create account</Button>
          </form>

          <p className="mt-5 text-center text-sm text-text-muted">
            Already have an account? <Link href="/login" className="text-accent hover:underline">Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
