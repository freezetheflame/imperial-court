// MemorialsPage — the emperor's inbox: submitted memorials with verdicts.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Memorial } from "../lib/api";

const VERDICT_LABELS: Record<string, string> = {
  approved: "准",
  rejected: "驳",
  held: "留中",
  returned: "发回重办",
};

export function MemorialsPage() {
  const qc = useQueryClient();
  const { data: memorials, isLoading } = useQuery({
    queryKey: ["memorials"],
    queryFn: () => api.listMemorials(),
  });

  const verdict = useMutation({
    mutationFn: ({ id, v }: { id: string; v: string }) =>
      api.verdictMemorial(id, v, "朱批"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memorials"] }),
  });

  if (isLoading) return <div>加载奏折…</div>;

  return (
    <section>
      <h2>奏折</h2>
      {memorials?.length === 0 && <p>暂无奏折。下达上谕后，丞相与各岗位的汇报会呈到这里。</p>}
      {memorials?.map((m: Memorial) => (
        <article
          key={m.id}
          style={{
            border: "1px solid #ddd",
            borderRadius: 8,
            padding: "1rem",
            marginBottom: "1rem",
            background: "#fdf8f0",
          }}
        >
          <header style={{ display: "flex", justifyContent: "space-between" }}>
            <strong>#{m.id}</strong>
            <span style={{ color: m.status === "submitted" ? "#8b1a1a" : "#666" }}>
              {m.status}
            </span>
          </header>
          <p style={{ margin: "0.5rem 0" }}>{m.content}</p>
          {m.status === "submitted" && (
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
              {Object.entries(VERDICT_LABELS).map(([v, label]) => (
                <button
                  key={v}
                  onClick={() => verdict.mutate({ id: m.id, v })}
                  disabled={verdict.isPending}
                  style={{
                    padding: "0.3rem 0.8rem",
                    border: "1px solid #8b1a1a",
                    borderRadius: 4,
                    background: "#fff",
                    color: "#8b1a1a",
                    cursor: "pointer",
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          )}
          {m.verdict && (
            <p style={{ color: "#8b1a1a", marginTop: "0.5rem" }}>批红：{VERDICT_LABELS[m.verdict] ?? m.verdict}</p>
          )}
        </article>
      ))}
    </section>
  );
}
