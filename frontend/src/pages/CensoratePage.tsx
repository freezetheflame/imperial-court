import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Impeachment } from "../lib/api";

const TYPE_LABELS: Record<string, string> = { tool_violation: "越权用器", comm_violation: "违制通信", dereliction: "失职" };

export function CensoratePage() {
  const qc = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const { data: overview } = useQuery({ queryKey: ["censorate", "overview"], queryFn: () => api.censorateOverview() });
  const { data: impeachments = [] } = useQuery({ queryKey: ["impeachments"], queryFn: () => api.listImpeachments() });
  const verdict = useMutation({ mutationFn: ({ id, value }: { id: string; value: string }) => api.verdictImpeachment(id, value, "朱批"), onSuccess: () => { qc.invalidateQueries({ queryKey: ["impeachments"] }); qc.invalidateQueries({ queryKey: ["censorate"] }); qc.invalidateQueries({ queryKey: ["posts"] }); } });

  return <section className="side-scene censorate-scene">
    <div className="archive-shelves" aria-hidden="true"><i /><i /><i /><i /></div>
    <header className="scene-heading"><div><span>肃纪纠察 · CENSORATE</span><h1>御史台案卷库</h1><p>台阁森然，诸案封存于此，候圣裁。</p></div><NavLink to="/" className="return-token">回銮金殿</NavLink></header>
    <div className="register-strip">{[["在审", overview?.pending_impeachments], ["待裁", overview?.pending_verdicts], ["违制", overview?.recent_violations], ["警告", overview?.warnings_issued], ["革职", overview?.removals]].map(([label, value]) => <div key={label as string}><strong>{value ?? 0}</strong><span>{label}</span></div>)}</div>
    {!impeachments.length && <div className="scene-empty">案架清肃，暂无弹劾卷宗。</div>}
    <div className="dossier-shelf">{impeachments.map((imp: Impeachment, index) => {
      const open = openId === imp.id;
      return <article key={imp.id} className={`dossier ${open ? "open" : ""}`} style={{ "--dossier-index": index } as React.CSSProperties}>
        <button className="dossier-spine" onClick={() => setOpenId(open ? null : imp.id)} aria-expanded={open}><span className="dossier-number">案 {String(index + 1).padStart(2, "0")}</span><strong>弹劾<br />{imp.target_post_title ?? imp.target_post}</strong><i>{TYPE_LABELS[imp.type] ?? imp.type}</i><b className={imp.status === "pending" ? "pending" : "closed"}>{imp.status === "pending" ? "待裁" : "已断"}</b></button>
        {open && <div className="dossier-sheet"><button className="sheet-close" onClick={() => setOpenId(null)}>合卷</button><span className="folio-kicker">御史台封呈 · {imp.id}</span><h2>弹劾 {imp.target_post_title ?? imp.target_post}</h2><dl><dt>案由证据</dt><dd>{imp.evidence}</dd>{imp.brief && <><dt>调查简报</dt><dd>{imp.brief}</dd></>}<dt>台议</dt><dd className="recommendation">{imp.recommendation === "removal" ? "革职查办" : imp.recommendation === "warning" ? "留任警告" : "尚未拟议"}</dd></dl>{imp.status === "pending" && imp.recommendation && <div className="folio-verdicts"><button onClick={() => verdict.mutate({ id: imp.id, value: "approve" })} disabled={verdict.isPending}>朱批 · 准奏</button><button onClick={() => verdict.mutate({ id: imp.id, value: "reject" })} disabled={verdict.isPending}>朱批 · 驳回</button></div>}{imp.verdict && <div className="red-verdict">圣裁 · {imp.verdict}</div>}</div>}
      </article>;
    })}</div>
  </section>;
}
