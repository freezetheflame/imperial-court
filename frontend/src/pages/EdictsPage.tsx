import type { FormEvent } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Edict } from "../lib/api";

export function EdictsPage() {
  const qc = useQueryClient(); const { data: edicts } = useQuery({ queryKey: ["edicts"], queryFn: () => api.listEdicts() });
  const [title, setTitle] = useState(""); const [taskType, setTaskType] = useState("research"); const [description, setDescription] = useState(""); const [target, setTarget] = useState("");
  const create = useMutation({ mutationFn: () => api.createEdict({ title, task_type: taskType, description, target: target || null }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["edicts"] }); setTitle(""); setDescription(""); setTarget(""); } });
  function onSubmit(e: FormEvent) { e.preventDefault(); if (title && description) create.mutate(); }
  return <section><div className="page-heading"><div><div className="eyebrow">御旨 · EDICTS</div><h2>拟旨下谕</h2><p>一言九鼎，定分止争。请陛下明示所命。</p></div><span className="seal">皇帝<br />御笔</span></div>
    <form onSubmit={onSubmit} className="panel" style={{ padding: "26px", marginBottom: 34, position: "relative" }}><div style={{ textAlign: "center", borderBottom: "1px solid #b7884848", paddingBottom: 18, marginBottom: 22 }}><div className="eyebrow">拟旨 · 敕令草本</div><h3 style={{ margin: "7px 0 0", fontSize: "1.5rem", letterSpacing: ".16em" }}>奉天承运 · 皇帝诏曰</h3></div>
      <div style={{ display: "grid", gap: 17 }}><label className="field">诏令标题<input value={title} onChange={e => setTitle(e.target.value)} required placeholder="如：整理部门季度报告" /></label><label className="field">事务类别<select value={taskType} onChange={e => setTaskType(e.target.value)}><option value="research">研究</option><option value="report_compile">报告整理</option><option value="data_analysis">数据分析</option><option value="communication">对外沟通</option><option value="general">一般事务</option></select></label><label className="field">诏令正文<textarea value={description} onChange={e => setDescription(e.target.value)} required rows={4} placeholder="明示任务内容与所期成果……" /></label><label className="field">着令岗位（可选）<input value={target} onChange={e => setTarget(e.target.value)} placeholder="留空则由丞相酌定，如 finance / justice" /></label></div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, marginTop: 22, flexWrap: "wrap" }}><span className="eyebrow">朱批御印 · 即刻传旨</span><button className="action-btn" type="submit" disabled={create.isPending}>{create.isPending ? "传旨中……" : "颁布上谕"}</button></div>{create.isError && <p style={{ color: "#a51f1f", margin: "14px 0 0" }}>{(create.error as Error).message}</p>}
    </form>
    <div className="eyebrow" style={{ marginBottom: 12 }}>历代上谕 · ARCHIVES</div><div style={{ display: "grid", gap: 12 }}>{edicts?.map((e: Edict) => <article className="paper" key={e.id} style={{ padding: "18px 22px 18px 28px" }}><div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}><strong>{e.title}</strong><span style={{ color: "#8b1a1a", fontSize: ".8rem" }}>{e.status}</span></div><p className="paper-content" style={{ margin: "10px 0 0", fontSize: ".93rem" }}>{e.formal_text || "诏令正文尚在拟定。"}</p></article>)}</div>
  </section>;
}
