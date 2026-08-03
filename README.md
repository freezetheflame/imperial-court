# Imperial Court (朝堂)

一个"制度是一等公民"的多 agent 编排系统：古代政治制度作为**可换装的编排层**，严格约束每个 agent 的岗位职责、职权边界、通信协议与汇报链路。皇帝（用户）下达上谕（任务）、审批奏折（汇报）、裁决弹劾（御史台）；前端为沉浸式宫廷界面。

> 制度不是装饰，而是系统的核心抽象。换制度 = 换配置文件；agent 的行为边界由规则引擎硬约束，不依赖 LLM 自觉。

## 核心特性

- **制度换装**：制度定义角色体系、职权边界、通信协议、汇报链路、权力制衡；当前内置三公九卿（简化版：3 公 + 4 部 + 御史助手 = 8 岗位），可扩展三省六部等
- **严禁越权**：工具白名单 + 消息路由拦截双重硬约束；确定性判定由规则引擎执行，绝不交给 LLM
- **权力制衡**：御史台监察弹劾（特权直奏）、皇帝朱批裁决、革职/留任警告职位变动
- **真实 agent 网络**：消息总线驱动各岗位 agent（LLM）自主工作——皇帝下旨后，丞相拆解分派、执行岗干活回报、御史台监察，全自动流转
- **沉浸式皇帝体验**：奏折/朱批/拟旨/官职墙/御史台案卷，SSE 实时推送，宫廷风格 UI

## 真实运行效果（DeepSeek flash 实测）

```
🏛️ 皇帝下旨「整理第三季度业绩报告」
→ 丞相 agent：拆解上谕为 2 个子任务，分派治粟内史
→ 治粟内史 agent：run_task 执行 → report_result 回报丞相
→ 丞相 agent：汇总复核，呈报奏折
   「一、总体情况… 二、增长部门：典客对外交流环比增长约12%…」
✍️ 皇帝批红：approved
```

每一环都是真实 LLM agent 在思考、调用工具、按制度流转。演示中曾出现丞相 agent 试图越权调用执行工具，被规则引擎拦截并主动承认"不在丞相职权范围内，符合铁律"——制度硬约束真实生效。

## 架构分层

```
Frontend (React+Vite+TS+Tailwind)  ← HTTP + SSE
  ↓
API Layer (FastAPI)                ← 契约校验、SSE 推送
  ↓
Court Domain                       ← 上谕/奏折/弹劾/任命服务
  ↓
Message Bus (asyncio)              ← 路由校验(白名单) + 审计
  ↓
Agent Layer (薄循环)               ← AgentLoop / LLMClient / 工具
  ↓
Rule Engine                        ← 静态查表 + 动态策略
  ↓
Storage (SQLite)                   ← 事件表 = 史册 = 御史台数据源
```

## 文档

- [需求基线](docs/requirements.md) — grill-me 确认的全部决策
- [架构设计](docs/architecture.md) — 分层、模块、表结构、流程
- [API 契约](docs/api-contract.md) — 前端开发契约
- [前端设计指令](docs/frontend-design-brief.md) — 沉浸式 UI 设计规范

## 目录结构

```
imperial-court/
├── backend/
│   ├── institutions/          # 制度定义（YAML，一等公民）
│   │   └── sanguan-jiuqing.yaml
│   ├── imperial/              # Python 包
│   │   ├── institution/       # 制度加载与校验
│   │   ├── rule_engine/       # 规则引擎（静态+动态）
│   │   ├── bus/               # 异步消息总线
│   │   ├── agent/             # 薄循环/LLM客户端/工具/调度器
│   │   ├── court/             # 领域服务（上谕/奏折/弹劾/任命）
│   │   ├── storage/           # SQLite 薄封装
│   │   └── api/               # FastAPI 路由 + SSE + bootstrap
│   ├── scripts/               # demo_court.py 真实端到端演示
│   └── tests/                 # 65+ 测试（协议层/行为层/API/调度器）
├── frontend/                  # React + Vite + TS + Tailwind
└── docs/                      # 需求/架构/契约/设计指令
```

## 快速开始

```bash
# 1. 后端（Python ≥3.10，uv 管理）
cd backend
uv venv --python 3.12
uv pip install -e ".[dev]"
# 配置 LLM（DeepSeek 或任意 OpenAI 兼容端点）
cp .env.example .env   # 填入 IMPERIAL_LLM_API_KEY
uv run uvicorn imperial.api.main:app --reload   # http://localhost:8000

# 2. 前端
cd frontend
npm install
npm run dev            # http://localhost:5173

# 3. 真实 agent 端到端演示（可选）
cd backend
.venv/bin/python -m scripts.demo_court
```

## 测试

```bash
cd backend
.venv/bin/python -m pytest tests/     # 65 passed + 3 skipped(需真key的integration)
```

## 平台

早期在 Kylin Linux (aarch64) 开发，目标平滑迁移 Windows/WSL (x86_64)。路径用 pathlib，无平台分支。

## 未来改进方向

### 治理机制
- [ ] **权限矩阵（C 层）**：越权控制从"工具白名单 + 消息路由拦截"（A+B）演进为完整权限矩阵——岗位 × 动作 × 资源 三层拦截，数据层访问也受控。规则引擎 `judge()` 接口已预留，内部加数据层判定即可
- [ ] **降职/调任**：职位变动从"革职 + 留任警告"两档扩展，支持权限收缩、汇报层级调整（如郎中降为员外郎）
- [ ] **皇帝主动查岗**：皇帝可主动要求御史台调查某岗位，或亲自查看履职流水（当前御史台只被动收弹劾）
- [ ] **弹劾升级路径**：御史台直奏后的完整廷议流程（如三公合议、证据复核会审）

### 编排能力
- [ ] **多任务聚合**：丞相等所有子任务回报后再统一上奏（当前每收到一个 result 呈一封奏折），需任务完成计数/状态跟踪
- [ ] **调度器接入 FastAPI**：下旨后自动触发 agent 网络运行，前端实时看到朝廷运转（当前演示是脚本驱动）
- [ ] **多执行岗并行**：一个上谕分派给多个岗位并行处理，跟踪各岗进度与汇总
- [ ] **自由拟旨**：上谕从结构化表单演进为自然语言解析（当前表单优先，可靠优先）

### 制度与模型
- [ ] **制度换装完善**：新增三省六部制（中书出令、门下封驳、尚书执行）等第二套制度，验证换装机制
- [ ] **模型可插拔**：丞相/御史大夫切换 deepseek-v4-pro（发布后）；接入 kimi 等更多 provider（OpenAI 兼容均支持）
- [ ] **agent 层智能测试档案**：沉淀各岗位场景剧本验收用例、失败记录、prompt 迭代历史，换制度时复用

### 基础设施
- [ ] **外部消息中间件**：吞吐成为瓶颈时，消息总线从进程内 asyncio 演进到 Redis Streams 等（消息 schema 已预留）
- [ ] **认证与多租户**：本地单机初版无认证，未来支持多用户/多"朝廷"实例
- [ ] **降级与容错**：LLM 调用失败重试/降级策略、agent 卡死超时、任务断点恢复
