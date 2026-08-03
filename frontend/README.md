# Imperial Court — 前端

React 19 + Vite 8 + TypeScript + Tailwind CSS v4 + TanStack Query + SSE。

## 开发

```bash
npm install
npm run dev        # http://localhost:5173 (Vite 默认端口)
```

后端需同时运行（uvicorn，见 ../backend/README）。默认 API base 是 `http://localhost:8000`，
可用环境变量覆盖：

```bash
VITE_API_BASE=http://localhost:8000 npm run dev
```

## 目录

```
src/
├── lib/
│   ├── api.ts             # 类型化 API client（对接 docs/api-contract.md）
│   └── useEventStream.ts  # SSE 实时事件 → query 失效
├── components/
│   └── Layout.tsx         # 侧边导航壳
├── pages/
│   ├── MemorialsPage.tsx  # 奏折（皇帝收件箱 + 批红）
│   ├── EdictsPage.tsx     # 上谕（下达表单 + 列表）
│   ├── CensoratePage.tsx  # 御史台（弹劾案 + 裁决）
│   └── PostsPage.tsx      # 官职墙（在职/空缺/任命）
└── main.tsx / App.tsx     # QueryClient + Router + SSE bridge
```

## 契约

前端只依赖 `docs/api-contract.md` 定义的 REST 端点 + SSE 事件名。
后端实现变动不影响前端（契约先行）。
