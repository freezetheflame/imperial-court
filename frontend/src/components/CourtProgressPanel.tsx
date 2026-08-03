// CourtProgressPanel — 政事进度：当前上谕的执行进度（卷轴风格）。
// 轮询后端 /api/edicts/{id}/progress；有进行中的上谕时显示。

import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { EdictProgress } from "../lib/api";

const STAGE_LABELS: Record<EdictProgress["stage"], string> = {
  pending: "丞相拟旨分派中",
  executing: "臣工办理中",
  done: "已办结呈奏",
};

export function CourtProgressPanel({ edictId, title }: { edictId: string; title: string }) {
  const { data } = useQuery({
    queryKey: ["edict-progress", edictId],
    queryFn: () => api.getEdictProgress(edictId),
    refetchInterval: 3000, // poll every 3s while open
  });

  const prog = data ?? {
    stage: "pending" as const,
    total: 0,
    done: 0,
    percent: 0,
    subtasks: [],
  };

  return (
    <div className="court-progress">
      <div className="progress-head">
        <span className="progress-eyebrow">政事进度</span>
        <span className="progress-stage">{STAGE_LABELS[prog.stage]}</span>
      </div>
      <div className="progress-title">{title}</div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${prog.percent}%` }} />
      </div>
      <div className="progress-meta">
        <span>
          {prog.done}/{prog.total || "—"} 事已毕 · {prog.percent}%
        </span>
        {prog.stage === "done" && <span className="progress-done">奏折已呈御前</span>}
      </div>
      {prog.subtasks.length > 0 && (
        <ul className="progress-subtasks">
          {prog.subtasks.map((s) => (
            <li key={s.key} className={s.completed ? "done" : ""}>
              <span className="subtask-mark">{s.completed ? "✓" : "○"}</span>
              <span className="subtask-title">{s.title}</span>
              <span className="subtask-target">{s.target}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
