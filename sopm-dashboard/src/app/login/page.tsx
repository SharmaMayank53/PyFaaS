"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { login } from "@/lib/api";
import { useAuthStore } from "@/store";
import { Activity } from "lucide-react";
import { Button, Input } from "@/components/ui";

function LoginForm() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { setToken } = useAuthStore();
  const router = useRouter();
  const searchParams = useSearchParams();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { access_token } = await login(username, password);
      setToken(access_token, username);
      router.push(searchParams.get("next") || "/");
    } catch {
      setError("Invalid credentials");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="mb-1.5 block text-xs text-text-muted">Username</label>
        <Input
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
          placeholder="admin"
        />
      </div>
      <div>
        <label className="mb-1.5 block text-xs text-text-muted">Password</label>
        <Input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
          placeholder="password"
        />
      </div>

      {searchParams.get("registered") && <p className="font-mono text-xs text-success">Account created. Sign in to continue.</p>}
      {error && <p className="font-mono text-xs text-error">{error}</p>}

      <Button type="submit" variant="primary" loading={loading} className="w-full py-2.5">
        Sign in
      </Button>
    </form>
  );
}

export default function LoginPage() {
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
          <h1 className="mb-1 text-lg font-semibold text-text-primary">Sign in</h1>
          <p className="mb-6 text-sm text-text-muted">Operations Dashboard</p>
          <Suspense fallback={<p className="text-sm text-text-muted">Loading sign in...</p>}>
            <LoginForm />
          </Suspense>
        </div>
      </div>
    </div>
  );
}


