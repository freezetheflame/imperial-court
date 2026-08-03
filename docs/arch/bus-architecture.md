# 通信总线架构（Message Bus Architecture）

> 朝廷的血管。所有消息经总线单点校验 + 全量审计，
> 违制消息被拦截并上报御史台。
> 本文描述 `imperial/bus/__init__.py`。

## 设计模型：进程内 asyncio 异步总线

单进程内，每个岗位一个收件箱（asyncio.Queue），
消息投递经路由层**单点校验**，通过才入队，违规则上报御史台。

```
post_message(frm, to, type, payload)
│
├── 1. 路由校验（RuleEngine.judge(SendMessageAction)）
│     ├── allowed → 审计 message_sent → 投递到 to 的收件箱
│     └── denied  → 审计 violation → 上报御史台（违制记录）
│
└── 2. 收件箱
      Bus._queues: {post_id: asyncio.Queue}
      pump(): 轮询所有收件箱 → 调用订阅 handler（如 agent worker）
```

## Message 结构

```python
@dataclass
class Message:
    id: str                # 唯一 id
    frm: str               # 发件岗位
    to: str                # 收件岗位
    type: str              # 消息类型（edict/task_assignment/result/aggregate/...）
    payload: dict | None   # 业务数据
    created_at: str
```

消息类型由**通信白名单**约束（YAML `communication` 段）：
- `emperor → chancery`: edict / correction
- `chancery → finance`: task_assignment
- `finance → chancery`: result
- `system → chancery`: aggregate（多任务聚合通知）
- `censor → emperor`: memorial（特权直奏）
- `chancery → emperor`: memorial（标准奏折）
- ...

## Bus 核心方法

```python
class Bus:
    async def subscribe(post_id, handler)      # 岗位 worker 注册
    async def post_message(frm, to, type, payload) -> (ok, decision)
    async def pump_once()                      # 处理一轮（测试）
    async def pump()                           # 后台循环（生产）
    def _audit(kind, post_id, detail)          # 写入事件流
    async def _forward_violation(...)          # 违制 → 御史台
```

## 违制处理：拦截 + 上报

```
post_message(违制)
├── 审计 violation（含 frm/to/type/拒绝原因）
├── 消息不投递（拒绝执行）
└── 违制记录投递到御史台（censor）
      ↓
  调度器 _handle_violation
      ↓
  御史 agent 评估 → 弹劾 or 记档
```

**关键设计**：违制消息**不投递**，但**违制记录投递**——
坏事没做成，但证据留下来了。御史台据此监察弹劾。

## 审计：事件流 = 史册

每次投递/拦截都写事件流（`events` 表）：

| 事件 kind | 触发 | 数据 |
|---|---|---|
| message_sent | 消息投递成功 | 决策、消息类型 |
| violation | 消息被拦截 | 拒绝原因 |
| tool_call | 工具调用 | 工具、决策 |
| edict | 上谕下发 | 上谕详情 |
| memorial | 奏折呈上 | 奏折详情 |
| memorial_verdict | 批红 | 朱批结果 |
| impeachment | 弹劾 | 案卷 |
| post_status | 职位变动 | 革职/任命 |

**事件流 = 御史台数据源**（御史 agent 用 query_events 查证）、
**= 史册**（全量可溯源）。审计是单点写入，保证完整。

## 为什么进程内 asyncio（而非 RabbitMQ）

**现在**：单机单进程，进程内总线足够且简单。
- 路由校验、审计、违制上报全部同步内聚
- 无外部依赖（少一个服务少一份坑）

**演进**（README 未来方向）：
- 吞吐/分布式成为瓶颈时 → Redis Streams / RabbitMQ
- 消息 schema 已预留（Message 结构稳定），换传输层不动业务

## 与调度器的关系

```
Bus（基础设施）          Scheduler（编排）
──────────────────────────────────────
post_message             
  → 校验/审计/投递        subscribe(post_id, handler)
  → 收件箱 queue          pump() 轮询 → handler(msg)
                          → _dispatch → _run_agent → AgentLoop
                          → 工具调用再 post_message（网络自传播）
```

Bus 只负责"消息能不能通、通没通、留没留痕"；
Scheduler 负责"消息到了 agent 怎么反应"。
职责分离，各自可独立测试。

## 真实教训

1. **pump 拆分**：早期 pump() 无限循环在测试中超时
   → 拆 pump_once()（测试）+ pump()（生产后台）
2. **同步 LLM 阻塞**：handler 里 agent 的同步 LLM 调用阻塞事件循环，
   bus pump 也卡住 → to_thread 修复（跨层同坑）
3. **违制消息不投递但证据投递**：早期拦截后直接丢弃，
   御史台无据可查 → 增加违制记录转发
