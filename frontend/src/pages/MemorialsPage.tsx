import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Memorial } from "../lib/api";

const VERDICT_LABELS: Record<string, string> = { approved: "准", rejected: "驳", held: "留中", returned: "发回重办" };

export function MemorialsPage() {
  const qc = useQueryClient();
  const { data: memorials, isLoading } = useQuery({ queryKey: ["memorials"], queryFn: () => api.listMemorials() });
  const verdict = useMutation({ mutationFn: ({ id, v }: { id: string; v: string }) => api.verdictMemorial(id, v, "朱批"), onSuccess: () => qc.invalidateQueries({ queryKey: ["memorials"] }) });
  return <section>
    <div className="page-heading"><div><div className="eyebrow">奏报 · MEMORIALS</div><h2>御览奏折</h2><p>批阅臣工所奏，朱批裁定国事。</p></div><span className="seal">御览<br />之宝</span></div>
    {isLoading && <p>正在传呈奏折……</p>}
    {!isLoading && memorials?.length === 0 && <div className="panel" style={{ padding: "48px 24px", textAlign: "center", color: "#806e5d" }}>暂无奏折，静候臣工呈报。</div>}
    <div style={{ display: "grid", gap: 18 }}>{memorials?.map((m: Memorial) => <article className={`paper ${m.is_urgent ? "urgent" : ""}`} key={m.id} style={{ padding: "22px 24px 22px 30px" }}>
      <header style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start", borderBottom: "1px solid #b7884828", paddingBottom: 12 }}><div><div className="eyebrow">{m.is_urgent ? "急奏 · 直达御前" : "臣工呈报"}</div><strong style={{ fontSize: "1.15rem" }}>{m.from_post_title ?? m.from_post} 谨奏</strong><div style={{ color: "#927b66", fontSize: ".78rem", marginTop: 3 }}>案卷 {m.id} · {m.created_at ? new Date(m.created_at).toLocaleString("zh-CN") : "日期未载"}</div></div><span style={{ color: m.status === "submitted" ? "#8b1a1a" : "#796d63", fontSize: ".8rem" }}>{m.status === "submitted" ? "待批红" : m.status}</span></header>
      <p className="paper-content" style={{ margin: "18px 0 14px", textIndent: "2em" }}>{m.content}</p>
      {m.status === "submitted" && <div style={{ display: "flex", gap: 8, flexWrap: "wrap", borderTop: "1px solid #b7884828", paddingTop: 14 }}>{Object.entries(VERDICT_LABELS).map(([v, label]) => <button className="action-btn" key={v} onClick={() => verdict.mutate({ id: m.id, v })} disabled={verdict.isPending}>{label}</button>)}</div>}
      {m.verdict && <div className="verdict-ink">朱批：{VERDICT_LABELS[m.verdict] ?? m.verdict}</div>}
    </article>)}</div>
  </section>;
}
