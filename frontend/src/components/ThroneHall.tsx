import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Memorial } from "../lib/api";
import { ChancellorArrival } from "./ChancellorArrival";
import type { PresentationStage } from "./ChancellorArrival";
import { CourtProgressPanel } from "./CourtProgressPanel";

const VERDICTS = { approved: "准奏", rejected: "驳回", held: "留中", returned: "发回重办" };

export function ThroneHall() {
  const qc = useQueryClient();
  const { data: memorialData, isLoading } = useQuery({ queryKey: ["memorials"], queryFn: () => api.listMemorials() });
  const { data: edicts } = useQuery({ queryKey: ["edicts"], queryFn: () => api.listEdicts(), refetchInterval: 5000 });
  const memorials = memorialData ?? [];
  const pending = useMemo(() => memorials.filter(m => m.status === "submitted"), [memorials]);
  // most recent edict that isn't yet fully done (its memorial may or may not exist)
  const activeEdict = useMemo(() => edicts?.[0] ?? null, [edicts]);
  const knownIds = useRef<Set<string> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [stage, setStage] = useState<PresentationStage>("idle");
  const [isCeremonial, setIsCeremonial] = useState(false);
  const [showDrawer, setShowDrawer] = useState(false);
  const selected = memorials.find(m => m.id === selectedId) ?? null;

  useEffect(() => {
    if (!memorialData) return;
    const ids = new Set(memorials.map(m => m.id));
    if (knownIds.current === null) { knownIds.current = ids; return; }
    const newcomer = memorials.find(m => !knownIds.current?.has(m.id) && m.status === "submitted" && m.from_post === "chancery");
    knownIds.current = ids;
    if (newcomer && stage === "idle") { setSelectedId(newcomer.id); setIsCeremonial(true); setStage("arriving"); }
  }, [memorialData, memorials, stage]);

  useEffect(() => {
    if (stage !== "arriving") return;
    const timer = window.setTimeout(() => setStage("presented"), 4000);
    return () => window.clearTimeout(timer);
  }, [stage]);

  useEffect(() => {
    if (stage !== "departing") return;
    const timer = window.setTimeout(() => { setStage("idle"); setSelectedId(null); setIsCeremonial(false); }, 1350);
    return () => window.clearTimeout(timer);
  }, [stage]);

  const verdict = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string }) => api.verdictMemorial(id, value, "朱批"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["memorials"] });
      if (isCeremonial) setStage("departing"); else setSelectedId(null);
    },
  });

  function openMemorial(m: Memorial) { setSelectedId(m.id); setIsCeremonial(false); setStage("idle"); setShowDrawer(false); }

  return <section className="throne-hall" aria-label="金銮殿">
    <div className="hall-ceiling"><div className="plaque">正大光明</div></div>
    <div className="hall-columns left"><i /><i /><i /></div><div className="hall-columns right"><i /><i /><i /></div>
    <div className="distant-doors"><span /><span /></div>
    <div className="hall-floor"><div className="imperial-way" /></div>
    <div className="dais"><span>丹陛</span></div>
    <div className="incense-burner"><i /><span /><b /></div>
    <div className="candle left"><i /></div><div className="candle right"><i /></div>
    <div className="hall-title"><span>奉天承运</span><h1>朕临金銮殿</h1><p>{isLoading ? "内侍正在点检奏章……" : pending.length ? `御案尚有 ${pending.length} 封奏折待批` : "四海清平，殿上暂无急奏"}</p></div>

    {activeEdict && <div className="hall-progress-slot"><CourtProgressPanel edictId={activeEdict.id} title={activeEdict.title} /></div>}

    <ChancellorArrival stage={stage} onSkip={() => setStage("presented")} />

    <div className="throne-actions">
      <NavLink to="/censorate" className="command-token"><small>移驾</small>御史台</NavLink>
      <NavLink to="/posts" className="command-token"><small>翻阅</small>百官名册</NavLink>
      <NavLink to="/edicts" className="command-token"><small>御笔</small>拟旨下谕</NavLink>
    </div>

    <div className="imperial-desk">
      <div className="brush-rack" aria-hidden="true"><i /><i /><span /><b /></div>
      <button className={`memorial-stack${pending.length ? " has-memorials" : ""}`} onClick={() => setShowDrawer(true)} aria-label="打开奏匣"><i /><i /><span>{memorials.length ? `${memorials.length} 奏在匣` : "奏匣已清"}</span></button>
      <div className="desk-edge"><span>日理万机</span></div>
    </div>

    {showDrawer && <div className="memorial-drawer" aria-label="奏匣">
      <button className="drawer-close" onClick={() => setShowDrawer(false)} aria-label="合上奏匣">×</button>
      <div className="drawer-head"><span>御案奏匣</span><b>{memorials.length} 封</b></div>
      {memorials.length === 0 && <p className="drawer-empty">匣中空空，尚无奏章呈上。</p>}
      <ul className="drawer-list">{memorials.map(m => <li key={m.id}>
        <button className={m.status === "submitted" ? "unread" : ""} onClick={() => openMemorial(m)}>
          <span className="drawer-mark">{m.status === "submitted" ? "未批" : VERDICTS[m.verdict as keyof typeof VERDICTS] ?? m.verdict}</span>
          <span className="drawer-from">{m.from_post_title ?? m.from_post}</span>
          <span className="drawer-preview">{m.content.slice(0, 24)}…</span>
        </button>
      </li>)}</ul>
    </div>}

    {selected && <div className={`memorial-scroll ${stage === "arriving" ? "arriving-scroll" : stage === "departing" ? "departing-scroll" : "open"}`}>
      <button className="scroll-close" onClick={() => { setSelectedId(null); setStage("idle"); setIsCeremonial(false); }} aria-label="合上奏折">×</button>
      <div className="scroll-roller top" /><div className="scroll-roller bottom" />
      <div className="scroll-body"><div className="scroll-meta">{selected.is_urgent ? "急奏直达" : "臣工谨奏"} · {selected.from_post_title ?? selected.from_post}</div><h2>奏折</h2><p>{selected.content}</p><div className="scroll-date">{selected.created_at ? new Date(selected.created_at).toLocaleString("zh-CN") : selected.id}</div>
        {selected.status === "submitted" && <div className="verdict-row">{Object.entries(VERDICTS).map(([value, label]) => <button key={value} onClick={() => verdict.mutate({ id: selected.id, value })} disabled={verdict.isPending}>{label}</button>)}</div>}
        {selected.verdict && <div className="red-verdict">朱批 · {VERDICTS[selected.verdict as keyof typeof VERDICTS] ?? selected.verdict}</div>}
      </div>
    </div>}
  </section>;
}
