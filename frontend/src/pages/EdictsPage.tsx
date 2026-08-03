import type { FormEvent } from "react";
import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Edict } from "../lib/api";

export function EdictsPage() {
  const qc = useQueryClient();
  const { data: edicts = [] } = useQuery({ queryKey: ["edicts"], queryFn: () => api.listEdicts() });
  const [title, setTitle] = useState(""); const [taskType, setTaskType] = useState("research"); const [description, setDescription] = useState(""); const [target, setTarget] = useState("");
  const [stamp, setStamp] = useState<"idle" | "falling" | "impressed">("idle"); const [openId, setOpenId] = useState<string | null>(null);
  const create = useMutation({ mutationFn: () => api.createEdict({ title, task_type: taskType, description, target: target || null }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["edicts"] }); setTitle(""); setDescription(""); setTarget(""); setStamp("impressed"); window.setTimeout(() => setStamp("idle"), 1200); }, onError: () => setStamp("idle") });
  function onSubmit(event: FormEvent) { event.preventDefault(); if (!title || !description || create.isPending || stamp === "falling") return; setStamp("falling"); window.setTimeout(() => create.mutate(), 520); }

  return <section className="side-scene edict-scene">
    <header className="scene-heading"><div><span>御笔亲裁 · IMPERIAL EDICT</span><h1>拟旨下谕</h1><p>御案铺诏，落玺即传天下。</p></div><NavLink to="/" className="return-token">回銮金殿</NavLink></header>
    <form className="edict-scroll" onSubmit={onSubmit}><div className="edict-roller top" /><div className="edict-roller bottom" /><div className="edict-paper"><div className="edict-cloud left">☁</div><div className="edict-cloud right">☁</div><span className="edict-kicker">奉天承运 · 皇帝诏曰</span><h2>{title || "诏令题名"}</h2><div className="edict-fields"><label>敕令名目<input required value={title} onChange={e => setTitle(e.target.value)} placeholder="在此题写旨意" /></label><label>事务类别<select value={taskType} onChange={e => setTaskType(e.target.value)}><option value="research">研究</option><option value="report_compile">报告整理</option><option value="data_analysis">数据分析</option><option value="communication">对外沟通</option><option value="general">一般事务</option></select></label><label className="wide">诏令正文<textarea required rows={5} value={description} onChange={e => setDescription(e.target.value)} placeholder="朕闻……今着臣工依旨办理。" /></label><label className="wide">着令岗位<input value={target} onChange={e => setTarget(e.target.value)} placeholder="留空则由丞相酌定" /></label></div><div className="edict-signoff">布告天下，咸使闻知。</div><button className="issue-edict" type="submit" disabled={create.isPending || stamp === "falling"}>{create.isPending ? "传旨中……" : "颁布上谕"}</button>{create.isError && <p className="form-error">{(create.error as Error).message}</p>}<div className={`imperial-stamp ${stamp}`}><span>受命<br />于天</span></div></div></form>
    <div className="edict-archive"><h2>已颁诏旨</h2>{!edicts.length && <p>诏匣尚空，静候圣命。</p>}{edicts.map((edict: Edict) => <article key={edict.id} className={openId === edict.id ? "unrolled" : ""}><button onClick={() => setOpenId(openId === edict.id ? null : edict.id)}><i /><strong>{edict.title}</strong><span>{edict.status}</span></button>{openId === edict.id && <div><span>奉天承运皇帝，诏曰：</span><p>{edict.formal_text || "旨意已颁，正文尚待誊录。"}</p><small>{edict.issued_at ? new Date(edict.issued_at).toLocaleString("zh-CN") : edict.id}</small></div>}</article>)}</div>
  </section>;
}
