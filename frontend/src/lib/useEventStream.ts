// useEventStream — subscribe to the backend SSE stream and revalidate
// queries on relevant events.

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { StreamEvent } from "./api";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// which query keys to invalidate when a stream event arrives
const EVENT_QUERY_MAP: Record<StreamEvent, string[]> = {
  edict: ["edicts"],
  memorial: ["memorials"],
  impeachment: ["impeachments", "censorate"],
  post_status: ["posts", "censorate"],
  ping: [],
};

export function useEventStream(): void {
  const qc = useQueryClient();
  const qcRef = useRef(qc);
  qcRef.current = qc;

  useEffect(() => {
    const es = new EventSource(`${BASE}/api/events/stream`);
    es.onmessage = () => {
      // named events arrive via addEventListener; onmessage is a fallback
    };
    for (const event of Object.keys(EVENT_QUERY_MAP) as StreamEvent[]) {
      es.addEventListener(event, () => {
        const keys = EVENT_QUERY_MAP[event];
        if (keys.length === 0) return;
        for (const key of keys) {
          qcRef.current.invalidateQueries({ queryKey: [key] });
        }
      });
    }
    es.onerror = () => {
      // EventSource auto-reconnects; nothing to do
    };
    return () => es.close();
  }, []);
}
