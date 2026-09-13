"use client";

import { useEffect, useRef, useCallback } from "react";
import type { WsEvent, WsEventType } from "@/types";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

type EventHandler = (event: WsEvent) => void;

interface UseWebSocketOptions {
  onEvent?: EventHandler;
  onConnect?: () => void;
  onDisconnect?: () => void;
  reconnectInterval?: number;
  enabled?: boolean;
}

export function useWebSocket({
  onEvent,
  onConnect,
  onDisconnect,
  reconnectInterval = 3000,
  enabled = true,
}: UseWebSocketOptions = {}) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const pingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onEventRef = useRef(onEvent);
  const onConnectRef = useRef(onConnect);
  const onDisconnectRef = useRef(onDisconnect);

  useEffect(() => {
    onEventRef.current = onEvent;
    onConnectRef.current = onConnect;
    onDisconnectRef.current = onDisconnect;
  }, [onConnect, onDisconnect, onEvent]);

  const connect = useCallback(() => {
    if (!mountedRef.current || !enabled) return;
    if (wsRef.current?.readyState === WebSocket.OPEN || wsRef.current?.readyState === WebSocket.CONNECTING) return;

    const token = typeof window !== "undefined" ? localStorage.getItem("sopm_token") : null;
    const url = `${WS_URL}/ws/dashboard${token ? `?token=${token}` : ""}`;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        onConnectRef.current?.();

        // Client-side keepalive ping every 25s
        if (pingRef.current) clearInterval(pingRef.current);
        pingRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 25_000);
      };

      ws.onmessage = (e) => {
        if (!mountedRef.current) return;
        try {
          const event = JSON.parse(e.data) as WsEvent;
          if (event.type !== "pong" && event.type !== "keepalive") {
            onEventRef.current?.(event);
          }
        } catch {
          // ignore malformed frames
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        if (pingRef.current) clearInterval(pingRef.current);
        wsRef.current = null;
        onDisconnectRef.current?.();
        // Reconnect
        reconnectRef.current = setTimeout(connect, reconnectInterval);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      reconnectRef.current = setTimeout(connect, reconnectInterval);
    }
  }, [enabled, reconnectInterval]);

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) connect();

    return () => {
      mountedRef.current = false;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      if (pingRef.current) clearInterval(pingRef.current);
      wsRef.current?.close();
    };
  }, [connect, enabled]);
}


