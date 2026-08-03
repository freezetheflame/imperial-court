// EdictsPage — issue a new edict (structured form) and list existing ones.

import type { FormEvent } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Edict } from "../lib/api";

export function EdictsPage() {
  const qc = useQueryClient();
  const { data: edicts } = useQuery({ queryKey: ["edicts"], queryFn: () => api.listEdicts() });

  const [title, setTitle] = useState("");
  const [taskType, setTaskType] = useState("research");
  const [description, setDescription] = useState("");
  const [target, setTarget] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.createEdict({
        title,
        task_type: taskType,
        description,
        target: target || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["edicts"] });
      setTitle("");
      setDescription("");
      setTarget("");
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (title && description) create.mutate();
  }

  return (
    <section>
      <h2>上谕</h2>

      <form
        onSubmit={onSubmit}
        style={{
          border: "1px solid #8b1a1a",
          borderRadius: 8,
          padding: "1rem",
          marginBottom: "1.5rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.6rem",
        }}
      >
        <h3>下达上谕</h3>
        <label>
          标题
          <input value={title} onChange={(e) => setTitle(e.target.value)} required style={inputStyle} />
        </label>
        <label>
          任务类型
          <select value={taskType} onChange={(e) => setTaskType(e.target.value)} style={inputStyle}>
            <option value="research">研究</option>
            <option value="report_compile">报告整理</option>
            <option value="data_analysis">数据分析</option>
            <option value="communication">对外沟通</option>
            <option value="general">一般事务</option>
          </select>
        </label>
        <label>
          任务描述
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
            rows={3}
            style={inputStyle}
          />
        </label>
        <label>
          目标岗位（留空由丞相酌定）
          <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder="如 finance / justice" style={inputStyle} />
        </label>
        <button
          type="submit"
          disabled={create.isPending}
          style={{ background: "#8b1a1a", color: "#fff", border: 0, borderRadius: 4, padding: "0.5rem", cursor: "pointer" }}
        >
          {create.isPending ? "下达中…" : "下达"}
        </button>
        {create.isError && <p style={{ color: "red" }}>{(create.error as Error).message}</p>}
      </form>

      <ul style={{ listStyle: "none", padding: 0 }}>
        {edicts?.map((e: Edict) => (
          <li key={e.id} style={{ borderBottom: "1px solid #eee", padding: "0.6rem 0" }}>
            <strong>{e.title}</strong> <span style={{ color: "#888" }}>({e.status})</span>
            <p style={{ margin: "0.2rem 0 0", color: "#555", fontSize: "0.9rem" }}>{e.formal_text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "0.4rem",
  borderRadius: 4,
  border: "1px solid #ccc",
  marginTop: "0.2rem",
};
