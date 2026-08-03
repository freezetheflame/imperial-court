// CensoratePage — the censorate workbench: overview, pending impeachments,
// and the emperor's verdicts.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Impeachment } from "../lib/api";

export function CensoratePage() {
  const qc = useQueryClient();
  const { data: overview } = useQuery({
    queryKey: ["censorate", "overview"],
    queryFn: () => api.censorateOverview(),
  });
  const { data: impeachments } = useQuery({
    queryKey: ["impeachments"],
    queryFn: () => api.listImpeachments(),
  });

  const verdict = useMutation({
    mutationFn: ({ id, v }: { id: string; v: string }) =>
      api.verdictImpeachment(id, v, "朱批"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["impeachments"] });
      qc.invalidateQueries({ queryKey: ["censorate"] });
      qc.invalidateQueries({ queryKey: ["posts"] });
    },
  });

  return (
    <section>
      <h2>御史台</h2>

      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", marginBottom: "1.5rem" }}>
        <Stat label="在审案件" value={overview?.pending_impeachments ?? 0} />
        <Stat label="待皇帝裁决" value={overview?.pending_verdicts ?? 0} />
        <Stat label="近期违制" value={overview?.recent_violations ?? 0} />
        <Stat label="已发警告" value={overview?.warnings_issued ?? 0} />
        <Stat label="已革职" value={overview?.removals ?? 0} />
      </div>

      <h3>弹劾案</h3>
      {impeachments?.length === 0 && <p>暂无弹劾案。</p>}
      {impeachments?.map((imp: Impeachment) => (
        <article
          key={imp.id}
          style={{
            border: "1px solid #ddd",
            borderRadius: 8,
            padding: "1rem",
            marginBottom: "1rem",
          }}
        >
          <header style={{ display: "flex", justifyContent: "space-between" }}>
            <strong>
              弹劾 {imp.target_post}（{imp.type}）
            </strong>
            <span style={{ color: imp.status === "pending" ? "#8b1a1a" : "#666" }}>{imp.status}</span>
          </header>
          <p style={{ margin: "0.5rem 0" }}>证据：{imp.evidence}</p>
          {imp.brief && <p style={{ color: "#555" }}>调查简报：{imp.brief}</p>}
          {imp.recommendation && (
            <p>
              御史台建议：
              <strong style={{ color: imp.recommendation === "removal" ? "#8b1a1a" : "#a67c00" }}>
                {imp.recommendation === "removal" ? "革职" : "留任警告"}
              </strong>
            </p>
          )}
          {imp.status === "pending" && imp.recommendation && (
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
              <button
                onClick={() => verdict.mutate({ id: imp.id, v: "approve" })}
                disabled={verdict.isPending}
                style={btnStyle("#8b1a1a")}
              >
                准（执行）
              </button>
              <button
                onClick={() => verdict.mutate({ id: imp.id, v: "reject" })}
                disabled={verdict.isPending}
                style={btnStyle("#666")}
              >
                驳回
              </button>
            </div>
          )}
          {imp.verdict && <p style={{ color: "#8b1a1a" }}>裁决：{imp.verdict}</p>}
        </article>
      ))}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: "0.6rem 1rem", minWidth: 100, textAlign: "center" }}>
      <div style={{ fontSize: "1.4rem", fontWeight: "bold", color: "#8b1a1a" }}>{value}</div>
      <div style={{ fontSize: "0.8rem", color: "#666" }}>{label}</div>
    </div>
  );
}

function btnStyle(color: string): React.CSSProperties {
  return {
    padding: "0.3rem 0.8rem",
    border: `1px solid ${color}`,
    borderRadius: 4,
    background: "#fff",
    color,
    cursor: "pointer",
  };
}
