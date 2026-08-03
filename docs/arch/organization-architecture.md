# 组织架构（Organization Architecture）

> 制度是组织的一等公民。朝廷怎么运转，由 YAML 说了算，不由代码说了算。
> 本文描述"制度-as-数据"的组织模型：岗位体系、汇报链路、权力制衡、人格画像。

## 核心命题

**制度不是装饰，而是系统的核心抽象。**
组织的一切规则——谁存在、谁能说什么、谁能做什么、向谁汇报、如何制衡——
都编码在制度文件里。换制度 = 换文件，任务与组织解耦。

## 制度文件（institution YAML）

```yaml
institution:
  id: sanguan-jiuqing
  name: 三公九卿（简化）
  schema_version: 3

posts:                     # 岗位体系（8 个）
  - id: chancery          # 丞相
    title: 丞相
    role: coordinator     # 角色：coordinator/executor/inspector/external
    reports_to: emperor
    model: deepseek-v4-flash
    persona: (LLM 生成)    # 人格画像存 posts.persona 列
  - id: finance
    title: 治粟内史
    role: executor
    reports_to: chancery
    ...

communication:            # 通信白名单（谁可以给谁发什么）
  - from: emperor
    to: chancery
    type: [edict, correction]
  - from: system
    to: chancery
    type: [aggregate]     # 多任务聚合通知
  - from: censor
    to: emperor
    type: [memorial]      # 御史台特权直奏（唯一例外链路）
  ...

tools:                    # 工具白名单（岗位能调用什么）
  chancery: [decompose_task, dispatch_task, submit_memorial, query_events, ...]
  finance: [run_task, report_result, ...]
  censor: [query_events, review_logs, open_impeachment, ...]
  ...

memorials:                # 奏折状态机
  initial: submitted
  states: [submitted, read, approved, rejected, held, returned, archived]
  verdicts: { approved: 准奏, rejected: 驳回, held: 留中, returned: 发回重办 }
```

## 岗位体系（Posts）

| 岗位 | 角色 | 汇报给 | 职责 |
|---|---|---|---|
| 丞相 chancery | coordinator | 皇帝 | 拆解上谕、分派任务、汇总奏折 |
| 太尉 grand_commandant | external | 皇帝 | 外联（预留） |
| 御史大夫 censor | inspector | 皇帝 | 监察百官、弹劾、特权直奏 |
| 御史 censor_assistant | inspector_assistant | 御史大夫 | 协理监察 |
| 治粟内史 finance | executor | 丞相 | 执行任务、回报 |
| 廷尉 justice | executor | 丞相 | 执行任务（质检） |
| 典客 relations | executor | 丞相 | 执行任务（外务） |
| 郎中令 internal | executor | 丞相 | 执行任务（内务兜底） |

**角色是抽象层**：`coordinator`（协调者）、`executor`（执行者）、
`inspector`（监察者）——制度换装时，同样的角色在不同制度下映射不同岗位。

## 汇报链路（标准 + 例外）

```
标准链路：执行岗 → 丞相 → 皇帝（奏折）
例外链路：御史台 → 皇帝（特权直奏，唯一绕过丞相的路径）
```

- 丞相分派任务给执行岗，执行岗回报丞相
- 丞相汇总所有子任务回报 → 呈奏折给皇帝
- 御史台发现违制 → 弹劾 → 皇帝裁决（革职需朱批）

## 权力制衡

```
皇帝 ──上谕──→ 丞相 ──分派──→ 执行岗
  ↑                  ↑            │
  │                  └──回报──────┘
  │  弹劾直奏         │
  └──←── 御史台 ←──违制上报──┘
        │
        └──弹劾──→ 皇帝裁决（革职需朱批）
```

- **皇帝**：最高权力，朱批裁决
- **丞相**：协调权，无执行权（尝试执行会被规则引擎拦截）
- **御史台**：监察权，可弹劾，但革职必须皇帝朱批
- **执行岗**：执行权，无决策权

## 人格画像（Persona）

每个岗位有一个"人"：名字、字、性情、施政风格、出身。
LLM 生成，让朝廷有血有肉。

```python
persona = {
    "name": "谢衡", "courtesy": "持中",
    "temperament": "沉稳果决，善谋善断",
    "style": "雷厉风行，赏罚分明",
    "origin": "以贤良方正举荐入仕",
}
```

**设计要点**：
- **姓氏去重**：生成时传入已用姓氏集合，LLM prompt 强制避开
  （真实踩过坑：8 个岗位全姓沈——LLM 姓氏同质化）
- **革职/任命自动换人**：remove 清空 persona 置空缺；appoint 生成新画像
- **惰性生成**：startup 后台生成，无 LLM 时模板兜底
- **存储**：posts.persona 列（JSON）

## 制度即数据 — 实证

开发中"皇帝 → 丞相 correction"白名单缺口被发现，
**零代码改动**，直接补在 YAML 通信规则里即可——制度缺口的闭合
发生在制度层，而不是代码层。这就是"制度是一等公民"的证明。

## 演进

- **权限矩阵（C 层）**：当前 A+B（工具白名单 + 消息路由拦截），
  演进为岗位 × 动作 × 资源三层拦截
- **三省六部制**：第二套制度文件验证换装机制
- **降职/调任**：职位变动从"革职+警告"扩展
