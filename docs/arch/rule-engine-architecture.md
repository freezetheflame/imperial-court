# 规则引擎架构（Rule Engine Architecture）

> 制度的"硬约束"落地处。确定性判定归规则引擎，智能判断归 LLM——
> 这条边界是整个系统可信的根基。
> 本文描述 `imperial/rule_engine/__init__.py`。

## 核心命题

**规则引擎是"铁律"，LLM 是"人"。**
- 违制与否（能不能发这条消息、能不能调这个工具）——**确定性判定，绝不交 LLM**
- 违制后怎么办（弹劾建议、证据评估）——LLM 智能判断
- LLM 可能胡说八道，但规则引擎不会——硬约束保证系统底线

## 统一判定入口

```
judge(Action) → RuleDecision
```

所有需要裁定"允许/拒绝"的行为都包装成 **Action**，交给统一入口。

## Action 协议

```python
class Action(Protocol):
    def kind(self) -> str: ...   # 'send_message' | 'call_tool' | 'transition_memorial'
    def as_dict(self) -> dict: ...
```

| Action | kind | 裁定内容 |
|---|---|---|
| SendMessageAction(frm, to, msg_type) | send_message | 通信白名单 |
| CallToolAction(post, tool) | call_tool | 工具白名单 |
| TransitionMemorialAction(...) | transition_memorial | 奏折状态机 |

## RuleDecision

```python
@dataclass
class RuleDecision:
    allowed: bool
    reason: str          # 允许/拒绝的原因
    kind: str            # 动作类型
    policy: str | None   # 命中的策略名（审计用）
```

`decision.as_dict()` 用于审计事件存储。

## 分层判定：静态查表 + 动态策略

```
judge(action)
├── 1. 静态查表（institution 数据）
│     send_message → can_send(frm, to, msg_type)     ← YAML 通信白名单
│     call_tool    → can_call_tool(post, tool)       ← YAML 工具白名单
│     transition   → 奏折状态机（verdict 即目标状态）
├── 2. 动态策略注册（Python 函数）
│     register_policy("censor_direct_memorial", fn)
│     fn(action) -> RuleDecision | None   # None = 不适用
└── 3. 默认拒绝（无策略匹配 → 拒绝）
```

**为什么双轨**：
- **静态 YAML**：制度可换装，规则进配置文件（`institution.yaml`）
- **动态策略**：无法用纯声明表达的业务规则（如"御史台直奏是唯一例外链路"），
  用 Python 策略函数注册
- **默认拒绝**：安全默认——没明确允许就是不允许

## 制度层：Institution 提供判定数据

```python
class Institution:
    def can_send(self, frm, to, msg_type) -> bool   # 通信白名单
    def can_call_tool(self, post_id, tool) -> bool   # 工具白名单
    def post(self, post_id) -> Post                  # 岗位定义
```

规则引擎从 Institution 读数据，Institution 从 YAML 加载——
**换制度 = 换 YAML，规则引擎代码零改动**。

## 边界：什么进规则引擎，什么进 LLM

| 判定 | 归属 | 理由 |
|---|---|---|
| 能发这条消息吗 | 规则引擎 | 确定性，必须硬约束 |
| 能调这个工具吗 | 规则引擎 | 确定性，必须硬约束 |
| 奏折状态合法吗 | 规则引擎 | 状态机，确定性 |
| 这算违制吗 | 规则引擎（白名单查表） | 确定性 |
| 违制严重吗 | 御史 agent（LLM） | 智能判断 |
| 该弹劾谁 | 御史 agent（LLM） | 智能判断 |
| 革职还是警告 | 御史 agent 建议 + 皇帝朱批 | 混合 |

## 奏折状态机

```
submitted → read → approved / rejected / held / returned
              ↘ archived
```

**verdict 即目标状态**：`verdict(memorial, "approved")` 直接把状态
迁到 approved——不跳步（不能从 submitted 直接 archived）。

## 真实教训

1. **LLM 越权被拦**：演示中丞相 agent 试图调用 run_task 自己干活，
   被 `judge(CallToolAction)` 拦截，agent 主动承认"不在职权范围内"——
   规则引擎不是摆设（这是系统的宣传亮点，也是设计验证）
2. **白名单缺口在制度层闭合**：`emperor→chancery correction` 类型缺失，
   YAML 补一行即可，零代码改动（制度即数据实证）
3. **默认拒绝**：宁可误拒不可误放——被拒后 LLM 收到原因可修正，
   误放则破坏系统底线
