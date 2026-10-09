// 朝房集议 — the agent playground: watch posts discuss topics live,
// open topics as the emperor, and speak into the room (御临).
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { CourtThread } from "../lib/api";

export function CourtroomPage() {
  const qc = useQueryClient();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [newTopic, setNewTopic] = useState("");
  const [speech, setSpeech] = useState("");
  const streamRef = useRef<HTMLDivElement>(null);

  const { data: room } = useQuery({ queryKey: ["court", "room"], queryFn: () => api.courtRoom() });
  const { data: posts = [] } = useQuery({ queryKey: ["posts"], queryFn: () => api.listPosts() });
  const { data: active } = useQuery({
    queryKey: ["court", "thread", activeId],
    queryFn: () => api.getCourtThread(activeId!),
    enabled: !!activeId,
  });

  const titles = useMemo(() => {
    const m: Record<string, string> = { emperor: "皇帝", system: "系统" };
    for (const p of posts) m[p.id] = p.title;
    return m;
  }, [posts]);

  const threads = useMemo(() => room?.threads ?? [], [room]);
  const shown: CourtThread | null = active ?? null;

  // auto-select the most recent thread
  useEffect(() => {
    if (!activeId && threads.length) setActiveId(threads[0].id);
  }, [activeId, threads]);

  // follow the conversation
  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [shown?.messages?.length, activeId]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["court"] });
  };
  const openThread = useMutation({
    mutationFn: (topic: string) => api.openCourtThread(topic),
    onSuccess: (t) => { setNewTopic(""); setActiveId(t.id); invalidate(); },
  });
  const speak = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) => api.speakInCourt(id, content),
    onSuccess: () => { setSpeech(""); invalidate(); },
  });

  const speakerClass = (frm: string) =>
    frm === "emperor" ? "court-msg imperial" : "court-msg official";

  return <section className="side-scene courtroom-scene">
    <div className="court-lanterns" aria-hidden="true"><i /><i /><i /></div>
    <header className="scene-heading">
      <div><span>百官集议 · COURT ROOM</span><h1>朝房</h1>
        <p>{room?.enabled ? `朝房已开，${room.participants.length} 员在列，每议题 ${room.max_turns} 轮熔断。` : "朝房已闭（court_room 未启用）。"}</p>
      </div>
      <NavLink to="/" className="return-token">回銮金殿</NavLink>
    </header>

    <div className="court-layout">
      {/* 议题签架 */}
      <aside className="court-threads" aria-label="议题架">
        <form className="court-new" onSubmit={e => { e.preventDefault(); if (newTopic.trim()) openThread.mutate(newTopic.trim()); }}>
          <input value={newTopic} onChange={e => setNewTopic(e.target.value)} placeholder="御笔新议题……" maxLength={200} />
          <button type="submit" disabled={!newTopic.trim() || openThread.isPending}>开议</button>
        </form>
        {threads.length === 0 && <p className="court-empty-side">尚无议题。</p>}
        <ul>
          {threads.map(t => <li key={t.id}>
            <button className={t.id === activeId ? "active" : ""} onClick={() => setActiveId(t.id)}>
              <span className={`court-status ${t.status}`}>{t.status === "open" ? "议中" : "已闭"}</span>
              <strong>{t.topic}</strong>
              <small>{titles[t.opened_by] ?? t.opened_by} 起议 · {t.turns} 言{t.last_message ? ` · ${(titles[t.last_message.frm] ?? t.last_message.frm)}：${t.last_message.content.slice(0, 12)}…` : ""}</small>
            </button>
          </li>)}
        </ul>
      </aside>

      {/* 集议长卷 */}
      <div className="court-main">
        {!shown && <div className="scene-empty">朝房寂然。开一议题，观百官如何议论。</div>}
        {shown && <>
          <div className="court-topic-bar">
            <h2>{shown.topic}</h2>
            <div className="court-fuse" title="轮次熔断：达到上限自动闭议">
              <i style={{ width: `${Math.min(100, (shown.turns / (room?.max_turns ?? 24)) * 100)}%` }} />
              <span>{shown.turns}/{room?.max_turns ?? 24} 言{shown.status === "closed" ? " · 已闭议" : ""}</span>
            </div>
          </div>
          <div className="court-stream" ref={streamRef}>
            {(shown.messages ?? []).length === 0 && <p className="court-empty-stream">议题方开，百官尚未进言。</p>}
            {(shown.messages ?? []).map(m => <article key={m.id} className={speakerClass(m.frm)}>
              <header>
                <b>{titles[m.frm] ?? m.frm}</b>
                {m.frm === "emperor" && <span className="imperial-seal">御</span>}
                <time>{m.created_at ? new Date(m.created_at + "Z").toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }) : ""}</time>
              </header>
              <p>{m.content}</p>
            </article>)}
          </div>
          {shown.status === "open" ? (
            <form className="court-speak" onSubmit={e => { e.preventDefault(); if (speech.trim()) speak.mutate({ id: shown.id, content: speech.trim() }); }}>
              <input value={speech} onChange={e => setSpeech(e.target.value)} placeholder="御临朝房，批示一言……" maxLength={2000} />
              <button type="submit" disabled={!speech.trim() || speak.isPending}>御言</button>
            </form>
          ) : <p className="court-closed-note">此议题已闭（轮次熔断）。可另开新议。</p>}
        </>}
      </div>
    </div>
  </section>;
}
