"use client";

/**
 * Sentinel AI — live incident stream hook.
 *
 * Connects to the backend WebSocket (api/websockets.py `/ws`) and invokes
 * `onUpdate` for every `incident_update` message that orchestrator.py's
 * `_broadcast()` fires, so the dashboard reflects status changes live without a
 * page refresh or waiting for the polling interval.
 *
 * Resilience: auto-reconnects with capped backoff, sends a keepalive ping, and
 * cleans up on unmount. The poll in the page remains as a fallback if the socket
 * is unavailable.
 *
 * The handshake is authenticated: the Clerk session token is passed as a
 * `?token=` query param, and the server registers the socket under the verified
 * tenant (org_id) and only pushes that tenant's incident updates.
 */

import { useEffect, useRef, useState } from "react";
import { getSessionToken } from "@/lib/api";

export interface IncidentUpdate {
  id: string;
  title?: string;
  status?: string;
  severity?: string | null;
}

interface WsMessage {
  type: string;
  data: IncidentUpdate;
}

function resolveWsUrl(): string | null {
  if (typeof window === "undefined") return null;
  const apiBase = process.env.NEXT_PUBLIC_API_URL;
  if (apiBase) {
    // http(s)://host -> ws(s)://host/ws
    return apiBase.replace(/^http/, "ws").replace(/\/$/, "") + "/ws";
  }
  // Same-origin fallback.
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

export function useIncidentStream(onUpdate: (update: IncidentUpdate) => void) {
  const [connected, setConnected] = useState(false);
  // Keep the latest callback without forcing reconnects when it changes.
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  useEffect(() => {
    const baseUrl = resolveWsUrl();
    if (!baseUrl) return;

    let ws: WebSocket | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempts = 0;
    let closedByUnmount = false;

    const connect = async () => {
      // Fetch a fresh token each connect — Clerk tokens are short-lived and a
      // reconnect may happen after the original has expired.
      const token = await getSessionToken();
      if (closedByUnmount) return;
      if (!token) {
        // Not authenticated yet; retry shortly.
        reconnectTimer = setTimeout(connect, 2000);
        return;
      }
      const url = `${baseUrl}?token=${encodeURIComponent(token)}`;
      ws = new WebSocket(url);

      ws.onopen = () => {
        attempts = 0;
        setConnected(true);
        // Keepalive — server replies "pong".
        pingTimer = setInterval(() => {
          if (ws?.readyState === WebSocket.OPEN) ws.send("ping");
        }, 25000);
      };

      ws.onmessage = (event) => {
        if (event.data === "pong") return;
        try {
          const msg: WsMessage = JSON.parse(event.data);
          if (msg.type === "incident_update" && msg.data?.id) {
            onUpdateRef.current(msg.data);
          }
        } catch {
          /* ignore malformed frames */
        }
      };

      ws.onclose = () => {
        setConnected(false);
        if (pingTimer) clearInterval(pingTimer);
        if (closedByUnmount) return;
        // Reconnect with capped exponential backoff (1s..15s).
        attempts += 1;
        const delay = Math.min(1000 * 2 ** attempts, 15000);
        reconnectTimer = setTimeout(connect, delay);
      };

      ws.onerror = () => ws?.close();
    };

    connect();

    return () => {
      closedByUnmount = true;
      if (pingTimer) clearInterval(pingTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  return { connected };
}
