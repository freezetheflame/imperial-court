// PostsPage — the wall of offices: current posts, vacancies, appointment.

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Post } from "../lib/api";

const ROLE_LABELS: Record<string, string> = {
  coordinator: "总协调",
  executor: "执行",
  inspector: "监察",
  inspector_assistant: "监察助手",
  external: "对外",
};

const STATUS_LABELS: Record<string, string> = {
  active: "在职",
  vacant: "空缺",
  removed: "革职",
};

export function PostsPage() {
  const qc = useQueryClient();
  const { data: posts } = useQuery({ queryKey: ["posts"], queryFn: () => api.listPosts() });
  const [agentName, setAgentName] = useState<Record<string, string>>({});

  const appoint = useMutation({
    mutationFn: ({ id, agent }: { id: string; agent: string }) =>
      api.appointPost(id, agent),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["posts"] }),
  });

  return (
    <section>
      <h2>官职墙</h2>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: "1rem" }}>
        {posts?.map((p: Post) => (
          <article
            key={p.id}
            style={{
              border: `1px solid ${p.status === "vacant" ? "#a67c00" : "#ddd"}`,
              borderRadius: 8,
              padding: "1rem",
              background: p.status === "vacant" ? "#fffbe6" : "#fff",
            }}
          >
            <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <strong>{p.title}</strong>
              <span style={{ fontSize: "0.8rem", color: p.status === "vacant" ? "#a67c00" : "#666" }}>
                {STATUS_LABELS[p.status] ?? p.status}
              </span>
            </header>
            <p style={{ margin: "0.4rem 0", fontSize: "0.85rem", color: "#555" }}>
              {ROLE_LABELS[p.role] ?? p.role} · {p.id}
              {p.model ? ` · ${p.model}` : ""}
            </p>
            {p.current_agent && <p style={{ fontSize: "0.8rem" }}>现任：{p.current_agent}</p>}

            {p.status === "vacant" && (
              <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.5rem" }}>
                <input
                  placeholder="agent 名"
                  value={agentName[p.id] ?? ""}
                  onChange={(e) => setAgentName((s) => ({ ...s, [p.id]: e.target.value }))}
                  style={{ flex: 1, padding: "0.3rem", borderRadius: 4, border: "1px solid #ccc" }}
                />
                <button
                  onClick={() => appoint.mutate({ id: p.id, agent: agentName[p.id] || `agent_${p.id}` })}
                  disabled={appoint.isPending}
                  style={{ background: "#8b1a1a", color: "#fff", border: 0, borderRadius: 4, padding: "0.3rem 0.6rem", cursor: "pointer" }}
                >
                  任命
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
