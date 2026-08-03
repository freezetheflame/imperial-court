# Agent 调度架构（Agent Scheduler Architecture）

> 调度器把"消息总线"变成"活的朝廷"：每个岗位的 agent 订阅自己的收件箱，
> 收到消息就用 AgentLoop 处理，工具调用通过总线继续传播——形成反应式 agent 网络。
> 本文描述 `imperial/agent/scheduler.py` 与 `tracker.py`。

## 设计模型：消息驱动的反应式网络

不是"中央调度器派活"，而是**每个岗位是一个独立 worker，
订阅自己的收件箱，消息到达即反应**。朝廷的"运转"是消息在网络中传播的自然结果：

```
皇帝下旨 ──→ emperor→chancery edict ──→ 丞相 worker 收件箱
                                           ↓ AgentLoop
                                      拆解 + 分派
                                           ↓ chancery→finance task_assignment
                                           ↓
                                      治粟内史 worker 收件箱
                                           ↓ AgentLoop
                                      run_task → report_result
                                           ↓ finance→chancery result
                                           ↓
                                      TaskTracker 计数（多任务聚合）
                                           ↓ 全部完成
                                      system→chancery aggregate
                                           ↓ AgentLoop 汇总
                                      呈奏折 ──→ 皇帝
```

## 核心类：AgentScheduler

```
AgentScheduler
├── _posts: list[str]                 # 所有岗位
├── _system_prompts: {post: prompt}   # 岗位角色定义
├── _running: set[str]                # single-flight 并发保护
├── tracker: TaskTracker              # 多任务聚合
├── edicts: EdictService              # 办结持久化
└── loop_factory(post_id) → AgentLoop # 注入（测试可替换为 FakeLLM）
```

**关键方法**：
- `start()`：每个岗位 `bus.subscribe(post_id, handler)`
- `pump_once()`：处理一轮所有收件箱消息（测试用）
- `pump()`：后台无限循环（生产，`asyncio.create_task`）
- `_dispatch(post_id, msg)`：消息路由（违制记录→弹劾、其他→agent）
- `_run_agent(post_id, msg)`：single-flight 检查 → AgentLoop.run
- `_post_agent_action()`：agent 跑完后决定是否上奏
- `_on_edict_complete(edict_id)`：聚合完成 → 持久化 + 发 aggregate

## 并发模型：single-flight

```
async def _run_agent(post_id, msg):
    if post_id in self._running:
        return              # 忙碌中，消息留在队列（不丢）
    self._running.add(post_id)
    try:
        ...AgentLoop.run...
    finally:
        self._running.discard(post_id)
```

- 每个岗位**同一时刻只处理一个消息**（单线程 agent，无共享状态）
- 忙碌时新消息留在队列，处理完当前再取——不丢不重
- LLM 调用经 `asyncio.to_thread` 线程化，不阻塞事件循环

## 多任务聚合（TaskTracker）

一个上谕可能拆成多个子任务、分给多个执行岗。
TaskTracker 跟踪每个上谕的子任务完成情况：

```
TaskTracker
├── _progress: {edict_id: EdictProgress}
│     EdictProgress.subtasks: {subtask_key: SubtaskState}
│        SubtaskState: {target, title, completed, summary}
└── _fired: set[edict_id]        # 每个上谕只触发一次聚合

register_subtask(edict_id, key, target, title)   # dispatch_task 时登记
complete_subtask(edict_id, key, summary) -> bool # report_result 时完成
snapshot(edict_id) -> {stage, total, done, percent, subtasks}  # 进度 API
```

**聚合流程**：
1. 丞相 `dispatch_task` → tracker 登记子任务（key=目标岗位）
2. 执行岗 `report_result` → tracker 标记完成
3. **所有子任务完成** → `_on_edict_complete` 触发一次：
   - `edicts.mark_completed()` 持久化（重启不丢）
   - 发 `system→chancery aggregate` 消息
4. 丞相收到 aggregate → AgentLoop 汇总 → **呈一封奏折**（不是每 result 一封）

**进度三阶段**（snapshot）：
- `pending`：上谕已下，丞相还在拆解（无子任务）
- `executing`：子任务存在，部分未完成
- `done`：全部完成（聚合已触发或存储推断）

## 存储兜底（重启不丢）

TaskTracker 是内存态，重启即空。进度 API 做存储推断兜底：

```
if tracker 无内存状态:
    查 edicts.status == 'completed' → done
    或该上谕已有奏折 → done
```

## FastAPI 集成

```
create_app()
  └─ startup:
       await scheduler.start()
       pump_task = asyncio.create_task(scheduler.pump())   # 后台运转
       await asyncio.to_thread(ctx.ensure_personas)        # 人格画像后台生成
  └─ shutdown:
       pump_task.cancel()
```

- `scheduler: true/false` 暴露在 /api/health（有 LLM key 即启用）
- 下旨 → 总线 → agent 网络自动运转 → 奏折 → SSE 推送前端

## 真实教训

1. **pump_once 一轮清空所有队列**：dispatch 和执行岗处理在同一轮，
   测试脚本必须**预先**设置好所有岗位的 FakeLLM（真实踩过的坑）
2. **同步阻塞毁一切**：agent 的同步 LLM 调用会冻住 FastAPI 事件循环
   → to_thread（与 agent-architecture 同坑）
3. **聚合时机**：早期"每 result 一奏"，丞相空奏/多奏 →
   改"全部完成才聚合呈奏"（一次上谕一份奏折）
4. **内存态丢失**：重启后进度归零 → 存储兜底（status + 奏折推断）
