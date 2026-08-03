# Imperial Court — 架构设计

> 原则：深模块（深接口浅实现）、单一接缝、接口即测试面。制度层与任务层严格解耦。
> 术语遵循 codebase-design：Module / Interface / Seam / Adapter / Depth。

## 1. 系统分层

```
┌─────────────────────────────────────────────────────┐
│  Frontend (React + Vite + TS + Tailwind)            │
│  皇帝界面 / 御史台工作台 / 官职墙 / SSE 实时状态      │
└───────────────▲─────────────────────────────────────┘
                │ HTTP + SSE
┌───────────────┴─────────────────────────────────────┐
│  API Layer (FastAPI)                                │
│  路由 / 契约校验 / SSE 推送 / 认证(初版无)           │
└───────────────▲─────────────────────────────────────┘
                │ 领域方法调用
┌───────────────┴─────────────────────────────────────┐
│  Court Domain (领域服务层)                           │
│  上谕服务 / 奏折状态机 / 弹劾服务 / 任命服务          │
└───────────────▲─────────────────────────────────────┘
                │ 消息对象投递
┌───────────────┴─────────────────────────────────────┐
│  Message Bus (asyncio 异步总线)                     │
│  路由校验(制度白名单) → 投递 → 审计入事件表           │
└───────────────▲─────────────────────────────────────┘
                │ 工具调用 / 消息收发
┌───────────────┴─────────────────────────────────────┐
│  Agent Layer (薄循环)                               │
│  AgentLoop / LLMClient / ToolRegistry               │
│  每岗位一个 agent 实例，挂制度授权的工具集           │
└───────────────▲─────────────────────────────────────┘
                │ 判定
┌───────────────┴─────────────────────────────────────┐
│  Rule Engine (规则引擎)                             │
│  静态查表(YAML白名单) + 动态策略函数                 │
└───────────────▲─────────────────────────────────────┘
                │ 读写
┌───────────────┴─────────────────────────────────────┐
│  Storage (SQLite 薄封装)                            │
└─────────────────────────────────────────────────────┘
```

依赖方向自上而下。Rule Engine 被 Bus 和 Agent 层共同调用；Storage 被 Domain 和 Rule Engine 调用。

## 2. 模块划分（深模块优先）

### 2.1 institution — 制度加载与校验
- **接口**：`load_institution(yaml_path) -> Institution`；`get_post(post_id) -> Post`
- **实现**：解析制度 YAML，校验 schema（岗位唯一、通信规则合法、工具白名单引用存在），产出内存模型
- **深度**：把"制度 = 数据"这个核心概念封成一个小接口；上层从不知道 YAML 细节
- 制度模型：
  ```yaml
  institution:
    id: sanguan-jiuqing
    name: 三公九卿（简化）
    posts:
      - id: chancery           # 丞相
        title: 丞相
        role: coordinator
        direct_reports: []     # 丞相直接对接皇帝
        tool_allowance: [decompose_task, dispatch_task, summarize, query_events]
      - id: grand_commandant    # 太尉
        title: 太尉
        role: external
        tool_allowance: [compose_message, query_contacts]
      - id: censor             # 御史大夫
        title: 御史大夫
        role: inspector
        direct_reports: []     # 特权直奏
        tool_allowance: [query_events, draft_impeachment, review_logs]
      - id: censor_assistant   # 御史（助手）
        title: 御史
        role: inspector_assistant
        reports_to: censor
      - id: finance            # 治粟内史/少府 → 财务资源岗
        title: 治粟内史
        role: executor
        reports_to: chancery
        tool_allowance: [run_task, query_events]
      - id: justice            # 廷尉 → 司法质检岗
        title: 廷尉
        role: executor
        reports_to: chancery
        tool_allowance: [run_task, review_output, query_events]
      - id: relations          # 典客/宗正 → 关系外部岗
        title: 典客
        role: executor
        reports_to: chancery
        tool_allowance: [run_task, compose_message, query_events]
      - id: internal           # 郎中令/卫尉/太仆/奉常 → 内务服务岗
        title: 郎中令
        role: executor
        reports_to: chancery
        tool_allowance: [run_task, query_events]
    communication_rules:
      # 谁可以给谁发什么类型的消息
      - from: any
        to: chancery
        type: [report, result]
      - from: chancery
        to: any_executor
        type: [task_assignment, inquiry, correction]
      - from: censor
        to: emperor          # 特权直奏
        type: [impeachment, memorial]
      - from: any
        to: censor
        type: [violation_record, query_response]
      - from: emperor
        to: chancery
        type: [edict]
      - from: emperor
        to: censor
        type: [verdict]       # 皇帝对弹劾的裁决
      - from: chancery
        to: emperor
        type: [memorial]      # 丞相汇总上奏
    emperor_ui:
      posts_display: [chancery, grand_commandant, censor, finance, justice, relations, internal]
  ```

### 2.2 rule_engine — 规则引擎
- **接口**：`judge(action: RuleAction, context: RuleContext) -> RuleDecision`
- **RuleAction**：`{"kind": "send_message"|"call_tool"|"transition_memorial", ...}`
- **RuleDecision**：`{"allowed": bool, "reason": str, "recorded": bool}`
- **实现**：静态白名单（从 Institution 生成查表）+ 动态策略函数（注册表）
- **静态判定**（确定性，不交 LLM）：通信白名单、工具白名单、奏折状态机合法迁移
- **动态策略**（Python 函数注册）：弹劾处理建议（调用御史 agent 前的预判）、返工路由决策
- **深度**：上层只调 `judge()`，不知道规则是查表还是策略函数；新增规则 = 注册函数或改 YAML，不改调用方

### 2.3 bus — 消息总线
- **接口**：
  - `post_message(msg: Message)` — 发消息（路由校验 + 审计）
  - `subscribe(post_id, handler)` — 订阅
  - `publish_event(event: Event)` — 领域事件广播（审计/推送）
- **Message**：`{id, from_post, to_post, type, payload, created_at, status}`
- **实现**：asyncio.Queue + 路由层（调用 rule_engine.judge）；校验不过 → 生成违制记录（violation_record）→ 通知御史台 + 拒绝投递
- **审计**：所有消息 + 拦截记录入事件表
- **深度**：agent 层不知道路由存在，只知道"发消息/收消息"；路由与审计全在总线内部

### 2.4 agent — 薄 agent 循环
- **接口**：`AgentRuntime.run_task(post_id, task) -> TaskResult`；`AgentRuntime.respond_to_message(msg) -> None`
- **实现**：
  - AgentLoop：LLM 调用 → 若返回工具调用 → 校验工具白名单 → 执行 → 结果回填 → 循环 → 直到结束
  - LLMClient：OpenAI 兼容协议封装（base_url + api_key + model 名），模型可插拔（每岗位可配不同 model）
  - ToolRegistry：工具注册（decompose_task, dispatch_task, run_task, review_output, compose_message, query_events, draft_impeachment...）+ 每岗位挂白名单
- **深度**：循环是一个通用执行引擎，不含制度逻辑；制度逻辑全在 bus 路由和 rule_engine 里
- **模型配置**：Institution YAML 或独立 config 里 `model: {default: flash, chancery: pro}`

### 2.5 court — 领域服务
- **EdictService**：皇帝表单 → 正式上谕 → 投递丞相
- **MemorialService**：奏折状态机（呈报→已读→批红→归档）；批红动作（准/驳/留中/发回重办）
- **ImpeachmentService**：违制记录 → 通知御史台 → 弹劾案 → 直奏皇帝 → 裁决 → 职位变动
- **AppointmentService**：革职（岗位置空）→ 皇帝任命（选现役 agent 或新建）；留任警告记档
- **深度**：每个 service 一个接缝，状态机显式建模，测试面清晰

### 2.6 storage — SQLite 薄封装
- **接口**：`db.execute(sql, params)` + 少量命名查询（get_memorials, get_events, get_posts...）
- **实现**：sqlite3 + 轻量封装（不引 ORM），schema 迁移用简单版本号
- 表结构见 §4

### 2.7 api — FastAPI
- **接口**：REST 路由 + SSE（/api/events 实时推送）
- 路由：上谕、奏折、弹劾、官职、事件流、御史台
- **契约**：见 docs/api-contract.md（交付 kimi 用）

## 3. 关键流程

### 3.1 上谕下发
1. 皇帝填结构化表单（任务类型/目标/约束/期限）→ POST /api/edicts
2. EdictService 生成上谕记录 → bus.post_message(emperor → chancery, type=edict)
3. 丞相收到 → decompose_task 拆解 → dispatch_task 分派给对应执行岗（可能多个并行）
4. 执行岗 run_task 干活 → 完成 → 报 result 给丞相
5. 丞相汇总 → 奏折（type=memorial）→ 皇帝

### 3.2 皇帝批红
1. 皇帝在奏折列表看到新奏折（SSE 实时推送）
2. 批红：准（归档）/ 驳（打回丞相重新分派）/ 留中（搁置）/ 发回重办（打回丞相）
3. 打回 → 丞相重新指定分工 → 新任务循环

### 3.3 弹劾
1. bus 路由拦截违制 → 生成违制记录 → 事件表 + 通知御史台
2. 御史（助手）查证（query_events / review_logs）→ 调查简报
3. 御史大夫判断 → 起草弹劾奏章（type=impeachment）→ 特权直奏皇帝
4. 皇帝裁决：准（革职，AppointmentService 执行）/ 驳（弹劾驳回，记档）
5. 轻微违制：御史大夫直接留任警告记档，不上奏

## 4. 数据表结构

```sql
-- 制度表
CREATE TABLE institutions (
  id TEXT PRIMARY KEY,          -- sanguan-jiuqing
  name TEXT NOT NULL,
  definition_yaml TEXT NOT NULL, -- 原始制度定义
  active INTEGER DEFAULT 0      -- 当前启用
);

-- 岗位表
CREATE TABLE posts (
  id TEXT PRIMARY KEY,          -- chancery, censor, finance...
  institution_id TEXT NOT NULL,
  title TEXT NOT NULL,          -- 丞相
  role TEXT NOT NULL,           -- coordinator/executor/inspector...
  reports_to TEXT,              -- 汇报对象（NULL=直奏皇帝）
  status TEXT DEFAULT 'active', -- active/vacant/removed
  model TEXT,                   -- 模型覆盖（NULL=默认）
  current_agent TEXT,           -- 现任 agent 标识
  created_at TEXT DEFAULT (datetime('now'))
);

-- 上谕表
CREATE TABLE edicts (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  form_data TEXT NOT NULL,      -- 结构化表单原始数据
  formal_text TEXT NOT NULL,    -- 正式上谕文本
  status TEXT DEFAULT 'pending',-- pending/in_progress/done/returned
  issued_by TEXT DEFAULT 'emperor',
  issued_at TEXT DEFAULT (datetime('now'))
);

-- 奏折表
CREATE TABLE memorials (
  id TEXT PRIMARY KEY,
  edict_id TEXT,                -- 关联上谕（可为空=主动奏报）
  from_post TEXT NOT NULL,      -- 呈报岗位
  to_post TEXT DEFAULT 'emperor',
  content TEXT NOT NULL,        -- 奏折正文
  status TEXT DEFAULT 'submitted', -- submitted/read/approved/rejected/held/returned/archived
  verdict TEXT,                 -- 批红内容
  created_at TEXT DEFAULT (datetime('now')),
  decided_at TEXT
);

-- 事件表（史册/审计流水）
CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT DEFAULT (datetime('now')),
  kind TEXT NOT NULL,           -- message_sent/message_blocked/tool_call/violation/impeachment/appointment/edict/memorial...
  post_id TEXT,                 -- 涉事岗位
  detail TEXT                   -- JSON 详情
);

-- 弹劾表
CREATE TABLE impeachments (
  id TEXT PRIMARY KEY,
  violation_event_id INTEGER,
  target_post TEXT NOT NULL,    -- 涉事岗位
  type TEXT NOT NULL,           -- tool_violation/comm_violation/dereliction
  evidence TEXT NOT NULL,       -- 证据摘要
  brief TEXT,                   -- 御史调查简报
  recommendation TEXT,          -- 拟处理意见 warning/removal
  status TEXT DEFAULT 'pending',-- pending/verdict_done/rejected
  verdict TEXT,                 -- 皇帝裁决 approve/reject
  decided_at TEXT
);

-- 职位变动记录
CREATE TABLE appointments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id TEXT NOT NULL,
  action TEXT NOT NULL,         -- appoint/remove/warn
  agent TEXT,                   -- 任命的新 agent
  reason TEXT,
  impeachment_id TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
```

## 5. 规则引擎判定接口

```python
# 统一判定入口
def judge(action: RuleAction, context: RuleContext) -> RuleDecision:
    # 1. 静态查表（从 institution 生成）
    # 2. 动态策略函数
    ...

# RuleAction 示例
{"kind": "send_message", "from": "finance", "to": "emperor", "type": "report"}       # → denied（标准链路不允许直奏）
{"kind": "send_message", "from": "censor", "to": "emperor", "type": "impeachment"}    # → allowed（特权直奏）
{"kind": "call_tool", "post": "justice", "tool": "dispatch_task"}                     # → denied（工具白名单外）
{"kind": "transition_memorial", "from": "submitted", "to": "approved"}                # → allowed（皇帝批红）
```

## 6. 测试策略落地

- **协议层**（tests/protocol/）：pytest + 假 LLM（不真正调 API）测循环、总线、路由、状态机
- **行为层**（tests/behavior/）：场景剧本（假 LLM 返回预置结果）验证各岗位行为；真 API 冒烟测试单独标记（integration）
- **测试档案**（tests/archive/）：验收用例、失败记录、prompt 迭代历史

## 7. 跨平台注意

- pathlib 处理路径；不依赖 Linux-only 库
- SQLite 为标准库，asyncio 为标准库，无平台差异
- 前端 Node 20 在 Windows/WSL 无碍；后端 Python 需 ≥3.9（pydantic v2），用 uv 管理独立环境
- 配置（模型、制度路径）走环境变量 + 默认值，不做平台分支

## 8. 演进预留

- 权限矩阵 C 层：rule_engine 的 judge() 接口不变，内部加数据层判定
- 多制度换装：institutions 表插新记录 + 前端切制度视图；岗位表重建
- 降职/调任：appointments 表加 action 类型，状态机扩展
- 外部中间件：bus 接口不变，换传输层
