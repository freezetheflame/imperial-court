# Agent 架构（Agent Architecture）

> 薄循环 + 现成 LLM SDK。Agent 是"有岗位的人"，不是通用助手。
> 本文描述 `backend/imperial/agent/` 的设计。

## 设计哲学

**Agent 是"有岗位的人"，不是通用助手。**
每个 agent 绑定一个岗位（post），岗位决定它能说什么、能做什么、向谁汇报。
agent 本身不知道制度——制度在规则引擎和消息总线里，agent 只按照
岗位 system prompt 思考和行动，越权行为会被硬约束拦截。

## 模块地图

```
imperial/agent/
├── llm_client.py     LLM 客户端（OpenAI 兼容，chat/responses 双模式）
├── loop.py           AgentLoop — 薄循环（核心）
├── tool_registry.py  工具注册表（schema 生成 + 白名单执行）
├── tools.py          12 个岗位工具（业务能力）
├── prompts.py        岗位 system prompt（角色定义）
├── scheduler.py      AgentScheduler — 消息驱动调度（另见 scheduler-architecture.md）
├── tracker.py        TaskTracker — 多任务聚合（另见 scheduler-architecture.md）
└── persona.py        PersonaService — 人格画像（另见 organization-architecture.md）
```

## AgentLoop — 薄循环

```
┌─────────────────────────────────────────────┐
│  AgentLoop.run(post_id, task)               │
│                                             │
│  for turn in range(max_turns):              │
│    resp = LLM(system_prompt, messages,      │  ← to_thread（不阻塞事件循环）
│                tool_schemas, model)         │
│    if no tool_calls:                        │
│      return AgentRunResult(content)         │  ← 说话即结束
│    for each tool_call:                      │
│      decision = engine.judge(CallToolAction)│  ← 规则引擎裁定
│      if allowed: execute → 审计 tool_call   │
│      if denied: 回填拒绝理由 → LLM 修正      │  ← 越权可被"教育"
│                                             │
└─────────────────────────────────────────────┘
```

**关键决策**：
- **薄**：循环本身不懂业务，只做"调 LLM → 裁定 → 执行 → 回填"四步
- **单线程**：每个 agent 一次处理一个任务（single-flight），避免共享状态
- **max_turns 预算**：防止 LLM 无限工具循环（默认 8-10）
- **越权回填**：被拒的工具调用把拒绝原因写回对话，LLM 可据此修正行为
- **线程化 LLM 调用**：`asyncio.to_thread` 包裹同步的 `complete()`，
  否则阻塞 FastAPI 共享事件循环（真实踩过的坑）

## LLMClient

```python
LLMClient(
    base_url="https://api.deepseek.com",   # OpenAI 兼容端点
    api_key=os.environ["IMPERIAL_LLM_API_KEY"],
    model="deepseek-v4-flash",
    max_tokens=4096, temperature=0.2,
)
resp = llm.complete(messages, tools, model=...)  # 同步，支持 per-call model 覆盖
```

- **OpenAI 兼容**：任何兼容端点可插拔（DeepSeek / 中转站 / 本地 vLLM）
- **双模式预留**：chat completions（现用）+ responses（codex 系模型）
- **reasoning_content 支持**：DeepSeek thinking 模式的思考内容在
  多轮工具调用时回传（不丢推理上下文）——真实踩过的坑
- **模型可覆盖**：岗位 YAML 里 `model:` 字段覆盖全局默认
  （如丞相用 pro、执行岗用 flash）

## ToolRegistry 与工具

```python
registry = ToolRegistry(whitelist=("run_task", "report_result", ...))
registry.register("run_task", fn, schema)      # 注册 + JSON schema
schemas = registry.schemas()                   # 给 LLM 的 tool definitions
result = await registry.execute(name, args, _post_id=post_id)  # 注入岗位身份
```

- **白名单**：`execute` 内部再过一遍规则引擎 `judge(CallToolAction)`，
  whitelist 与 rule_engine 双保险
- **`_post_id` 注入**：工具签名声明 `_post_id` 参数时，
  AgentLoop 自动注入当前岗位 id（如 `report_result` 知道自己是谁）
- **12 个工具**：decompose_task / dispatch_task / run_task / report_result /
  query_events / review_logs / submit_memorial / appoint_post / warn_post /
  dismiss_post / open_impeachment / submit_edict

## 工具审计

每个工具调用都写入事件流（`tool_call` 或 `violation`），
包含：岗位、工具名、决策（allowed/reason）、错误。
审计流 = 御史台数据源 = 史册。审计在 AgentLoop 内完成，
通过 `auditor` 回调注入（默认接 bus 审计）。

## 真实教训（开发中踩过的坑）

1. **同步 LLM 阻塞事件循环**：agent 干活时整个 API 冻结
   → `asyncio.to_thread` 解决
2. **DeepSeek reasoning_content 丢失**：多轮工具调用报错
   → assistant 消息带 reasoning_content 回传
3. **assistant 消息重复追加**：多个 tool_calls 时逐条追加完整消息
   → 一条 assistant 消息携带全部 tool_calls，再逐条 tool 结果
