# Imperial Court (朝堂)

一个"制度是一等公民"的多 agent 编排系统：古代政治制度作为可换装的编排层，严格约束每个 agent 的岗位职责、职权边界、通信协议与汇报链路。皇帝（用户）下达上谕、审批奏折、裁决弹劾；前端为沉浸式宫廷界面。

## 核心特性

- **制度换装**：制度定义角色体系、职权边界、通信协议、汇报链路、权力制衡；当前内置三公九卿（简化版），可扩展
- **严禁越权**：工具白名单 + 消息路由拦截双重硬约束；确定性判定由规则引擎执行，不依赖 LLM
- **权力制衡**：御史台监察弹劾、皇帝朱批裁决、革职/警告职位变动
- **沉浸式皇帝体验**：奏折/批红/上谕表单/官职墙/御史台工作台，SSE 实时推送

## 文档

- [需求基线](docs/requirements.md) — grill-me 确认的全部决策
- [架构设计](docs/architecture.md) — 分层、模块、表结构、流程
- [API 契约](docs/api-contract.md) — 前端开发契约（交付 kimi）

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
│   │   ├── agent/             # 薄 agent 循环 + LLM 客户端
│   │   ├── court/             # 领域服务（上谕/奏折/弹劾/任命）
│   │   ├── storage/           # SQLite 薄封装
│   │   └── api/               # FastAPI 路由 + SSE
│   └── tests/                 # 协议层 + 行为层测试
├── frontend/                  # React + Vite + TS + Tailwind
└── docs/
    ├── requirements.md
    ├── architecture.md
    └── api-contract.md
```

## 快速开始（开发中）

```bash
# 后端（需 Python ≥3.9，用 uv 管理）
cd backend
uv venv
uv pip install -e ".[dev]"
uv run uvicorn imperial.api.main:app --reload

# 前端
cd frontend
npm install
npm run dev
```

## 平台

早期在 Kylin Linux (aarch64) 开发，目标平滑迁移 Windows/WSL (x86_64)。路径用 pathlib，无平台分支。
