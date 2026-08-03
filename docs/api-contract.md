# Imperial Court — API 契约 v0.1

> 本文档是前端（kimi 落地）与后端之间的契约。后端实现以本文为准；前端照此开发，不依赖后端内部实现。
> 所有接口返回 JSON。SSE 端点用于实时状态推送。

## 基础约定

- Base URL: `http://localhost:8000`
- 初版无认证（本地单机）
- 时间格式: ISO 8601 UTC
- 错误格式: `{"detail": "错误描述"}`

## 资源概览

| 资源 | 端点 | 说明 |
|------|------|------|
| 上谕 | `/api/edicts` | 皇帝下达任务 |
| 奏折 | `/api/memorials` | 汇报与批红 |
| 弹劾 | `/api/impeachments` | 御史台弹劾案 |
| 官职 | `/api/posts` | 官职墙 |
| 事件流 | `/api/events` | 史册/审计 |
| 实时推送 | `/api/events/stream` | SSE |
| 御史台 | `/api/censorate` | 御史台工作台 |

---

## 1. 上谕（任务下达）

### POST /api/edicts — 下达上谕
请求体（结构化表单）：
```json
{
  "title": "整理部门季度报告",
  "task_type": "report_compile",
  "target": "finance",          // 目标岗位（可选，空=丞相自定）
  "description": "汇总 Q3 各部门数据成一份报告",
  "constraints": "格式参照去年模板，数据需核对",
  "deadline": "2026-08-10"
}
```
响应 `201`：
```json
{
  "id": "edict_001",
  "title": "整理部门季度报告",
  "formal_text": "奉天承运皇帝，诏曰：着治粟内史汇总 Q3 各部门数据，成报告一份……",
  "status": "pending",
  "issued_at": "2026-08-03T03:00:00Z"
}
```

### GET /api/edicts — 上谕列表
响应 `200`：`[{"id","title","status","issued_at"}, ...]`

### GET /api/edicts/{id} — 上谕详情
响应 `200`：完整上谕（含 form_data、formal_text、关联奏折列表）

---

## 2. 奏折（汇报与批红）

### GET /api/memorials?status=submitted — 奏折列表
响应 `200`：
```json
[
  {
    "id": "mem_001",
    "edict_id": "edict_001",
    "from_post": "chancery",
    "from_post_title": "丞相",
    "content": "……奏曰：治粟内史已呈报数据，经核无误，谨奏。",
    "status": "submitted",
    "created_at": "2026-08-03T05:00:00Z",
    "is_urgent": false
  }
]
```
`is_urgent=true` 表示弹劾直奏（御史台特权通道）。

### GET /api/memorials/{id} — 奏折详情
响应 `200`：完整奏折（含 verdict、decided_at）。

### POST /api/memorials/{id}/verdict — 皇帝批红
请求体：
```json
{
  "verdict": "approved",        // approved | rejected | held | returned
  "comment": "准。办得很好。"
}
```
响应 `200`：更新后的奏折。
- `approved` → 归档
- `rejected` / `returned` → 打回丞相重新分派（系统自动通知丞相）
- `held` → 留中搁置

---

## 3. 弹劾（御史台）

### GET /api/impeachments?status=pending — 弹劾列表
响应 `200`：
```json
[
  {
    "id": "imp_001",
    "target_post": "justice",
    "target_post_title": "廷尉",
    "type": "tool_violation",     // tool_violation | comm_violation | dereliction
    "evidence": "廷尉尝试调用 dispatch_task（不在白名单）",
    "brief": "调查简报：……",
    "recommendation": "warning",  // warning | removal
    "status": "pending",          // pending | verdict_done | rejected
    "created_at": "2026-08-03T06:00:00Z"
  }
]
```

### POST /api/impeachments/{id}/verdict — 皇帝裁决
请求体：
```json
{
  "verdict": "approve",          // approve | reject
  "comment": "革职。"
}
```
响应 `200`：更新后的弹劾案。`approve` 且 recommendation=removal → 执行革职，岗位变 vacant。

---

## 4. 官职墙

### GET /api/posts — 岗位列表
响应 `200`：
```json
[
  {
    "id": "chancery",
    "title": "丞相",
    "role": "coordinator",
    "status": "active",          // active | vacant | removed
    "current_agent": "agent_chn",
    "model": "pro",
    "reports_to": "emperor"
  }
]
```

### POST /api/posts/{id}/appoint — 任命（岗位空缺时）
请求体：
```json
{
  "agent": "agent_chn_2"        // 或留空让系统新建
}
```
响应 `200`：更新后的岗位。

---

## 5. 事件流（史册）

### GET /api/events?kind=violation&post_id=justice&limit=50 — 事件查询
响应 `200`：
```json
[
  {
    "id": 1024,
    "ts": "2026-08-03T06:00:00Z",
    "kind": "violation",          // message_sent/message_blocked/tool_call/violation/impeachment/appointment/edict/memorial
    "post_id": "justice",
    "detail": {"message": "...", "reason": "工具不在白名单"}
  }
]
```

---

## 6. 实时推送（SSE）

### GET /api/events/stream
事件类型（`event:` 字段）：
- `edict` — 新上谕下达
- `memorial` — 新奏折呈上
- `impeachment` — 新弹劾案
- `post_status` — 岗位状态变化（革职/任命）
- `agent_activity` — agent 工作状态（processing/done）

推送格式：
```
event: memorial
data: {"id": "mem_001", "from_post": "chancery", "status": "submitted"}
```

前端连接后，先拉一次 `GET /api/memorials` 全量，再增量收 SSE。

---

## 7. 御史台工作台

### GET /api/censorate/overview — 御史台概览
响应 `200`：
```json
{
  "pending_impeachments": 2,      // 在审案件数
  "pending_verdicts": 1,          // 待皇帝裁决数
  "recent_violations": 5,         // 近期违制记录数
  "warnings_issued": 3,           // 已发警告数
  "removals": 1                   // 已革职数
}
```

### GET /api/censorate/violations?limit=20 — 违制记录流水
响应 `200`：违制记录列表（kind=violation 的事件）。

---

## 待定 / 后续迭代

- 认证（本地单机初版无）
- 皇帝主动查岗/主动要求调查（初版不做）
- 降职/调任（初版只做革职+警告）
