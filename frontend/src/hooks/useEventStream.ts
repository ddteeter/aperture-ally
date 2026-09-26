import { useEffect, useRef, useState } from "react";
import type { CoachEvent } from "../api/types";
import { backoffMs } from "../lib/events";

export type ConnectionStatus = "connecting" | "open" | "reconnecting" | "closed";

export function eventsUrl(loc: Location = window.location): string {
  const proto = loc.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${loc.host}/api/events`;
}

/**
 * Subscribe to /api/events with exponential-backoff reconnect. `onEvent` receives every event;
 * `onReconnect` runs after every (re)open so the caller can refetch everything.
 */
export function useEventStream(onEvent: (ev: CoachEvent) => void, onReconnect: () => void): ConnectionStatus {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const cb = useRef({ onEvent, onReconnect });
  cb.current = { onEvent, onReconnect };

  useEffect(() => {
    let ws: WebSocket | null = null;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      try {
        ws = new WebSocket(eventsUrl());
      } catch {
        schedule();
        return;
      }
      ws.onopen = () => {
        attempt = 0;
        setStatus("open");
        // Every open (including the first): anything published before we subscribed was missed.
        cb.current.onReconnect();
      };
      ws.onmessage = (m) => {
        try {
          const ev = JSON.parse(String(m.data)) as CoachEvent;
          if (ev && typeof ev.type === "string") cb.current.onEvent(ev);
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        ws = null;
        if (!stopped) schedule();
      };
      ws.onerror = () => {
        ws?.close();
      };
    };
    const schedule = () => {
      setStatus("reconnecting");
      const delay = backoffMs(attempt++);
      timer = setTimeout(connect, delay);
    };
    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
      setStatus("closed");
    };
  }, []);

  return status;
}
