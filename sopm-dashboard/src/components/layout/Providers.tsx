"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getCurrentUser } from "@/lib/api";
import { useDashboardStore, useAuthStore } from "@/store";
import { Sidebar } from "@/components/layout/Sidebar";
import type { WsEvent } from "@/types";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

// ─── WebSocket Bridge (inside providers so it has store access) ────────────

function WsBridge() {
  const { pushWsEvent, setWsConnected } = useDashboardStore();
  const { isAuthenticated } = useAuthStore();

  useWebSocket({
    enabled: isAuthenticated,
    onConnect: () => setWsConnected(true),
    onDisconnect: () => setWsConnected(false),
    onEvent: (event: WsEvent) => pushWsEvent(event),
  });

  return null;
}

// ─── App Shell ─────────────────────────────────────────────────────────────

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);
  const { token, isAuthenticated, logout } = useAuthStore();
  const pathname = usePathname();
  const router = useRouter();
  const isLoginPage = pathname === "/login";

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;

    if (!token) {
      setAuthChecked(true);
      if (!isLoginPage) {
        router.replace("/login");
      }
      return;
    }

    setAuthChecked(false);
    getCurrentUser()
      .then(() => {
        setAuthChecked(true);
        if (isLoginPage) {
          router.replace("/");
        }
      })
      .catch(() => {
        logout();
        setAuthChecked(true);
        if (!isLoginPage) {
          router.replace("/login");
        }
      });
  }, [isLoginPage, logout, mounted, router, token]);

  useEffect(() => {
    if (!mounted || !authChecked) return;

    if (!token && !isLoginPage) {
      router.replace("/login");
      return;
    }

    if (token && isAuthenticated && isLoginPage) {
      router.replace("/");
    }
  }, [authChecked, isAuthenticated, isLoginPage, mounted, router, token]);

  if (isLoginPage) {
    return <>{children}</>;
  }

  if (!mounted || !authChecked) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bg-base text-sm text-text-muted">
        Loading dashboard...
      </div>
    );
  }

  if (!token || !isAuthenticated) {
    return null;
  }

  return (
    <div className="h-screen overflow-hidden bg-bg-base">
      <WsBridge />
      <Sidebar />
      <main className="h-screen min-w-0 overflow-y-auto pt-[6.75rem] md:ml-56 md:pt-0">
        <div className="max-w-[1400px] mx-auto px-6 py-6">
          {children}
        </div>
      </main>
    </div>
  );
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => queryClient);

  return (
    <QueryClientProvider client={client}>
      <AppShell>{children}</AppShell>
    </QueryClientProvider>
  );
}



