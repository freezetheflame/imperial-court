import { useState } from "react";
import { NavLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Post } from "../lib/api";

const ROLE_LABELS: Record<string, string> = { coordinator: "总揽中枢", executor: "奉旨执行", inspector: "监察百官", inspector_assistant: "协理监察", external: "典掌外务" };
const STATUS_LABELS: Record<string, string> = { active: "在职", vacant: "待任", removed: "革职" };

export function PostsPage() {
  const qc = useQueryClient();
  const { data: posts = [] } = useQuery({ queryKey: ["posts"], queryFn: () => api.listPosts() });
  const [openId, setOpenId] = useState<string | null>(null);
  const [agentName, setAgentName] = useState<Record<string, string>>({});
  const appoint = useMutation({
    mutationFn: ({ id, agent }: { id: string; agent: string }) => api.appointPost(id, agent),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["posts"] }),
  });

  return <section className="side-scene roster-scene">
    <header className="scene-heading"><div><span>铨选百官 · IMPERIAL ROSTER</span><h1>百官名册</h1><p>展卷察官守，缺位者候旨补授。</p></div><NavLink to="/" className="return-token">回銮金殿</NavLink></header>
    <div className="roster-book"><div className="book-seam" /><div className="book-title">大朝官员名录</div><div className="roster-grid">{posts.map((post: Post) => {
      const open = openId === post.id;
      const person = post.persona;
      return <article key={post.id} className={`official-plaque ${post.status} ${open ? "open" : ""}`}>
        <button className="plaque-summary" onClick={() => setOpenId(open ? null : post.id)} aria-expanded={open}>
          <span>{ROLE_LABELS[post.role] ?? post.role}</span>
          <strong>{post.title}</strong>
          {person && !open && <em className="plaque-person">{person.name}<small>字{person.courtesy}</small></em>}
          <i>{post.id}</i>
          <b>{STATUS_LABELS[post.status] ?? post.status}</b>
        </button>
        {open && <div className="plaque-detail">
          {person ? (
            <div className="persona-card">
              <div className="persona-name">{person.name}<span>字{person.courtesy}</span></div>
              <dl>
                <dt>性情</dt><dd>{person.temperament}</dd>
                <dt>施政</dt><dd>{person.style}</dd>
                <dt>出身</dt><dd>{person.origin}</dd>
                <dt>官署</dt><dd>{post.id} · {ROLE_LABELS[post.role] ?? post.role}{post.reports_to ? ` · 隶属${post.reports_to}` : ""}</dd>
              </dl>
            </div>
          ) : (
            <dl>
              <dt>职掌</dt><dd>{ROLE_LABELS[post.role] ?? post.role}</dd>
              <dt>品秩</dt><dd>{post.model ?? "未定"}</dd>
              <dt>隶属</dt><dd>{post.reports_to ?? "御前直辖"}</dd>
              <dt>现任</dt><dd>虚位以待</dd>
            </dl>
          )}
          {post.status === "vacant" && <div className="appointment-box">
            <label>拟任人选<input value={agentName[post.id] ?? ""} onChange={e => setAgentName(state => ({ ...state, [post.id]: e.target.value }))} placeholder="留空由吏部选派" /></label>
            <button onClick={() => appoint.mutate({ id: post.id, agent: agentName[post.id] || `agent_${post.id}` })} disabled={appoint.isPending}>盖印任命</button>
          </div>}
        </div>}
      </article>;
    })}</div></div>
  </section>;
}
