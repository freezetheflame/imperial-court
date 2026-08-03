# 前端架构（Frontend Architecture）

> 从"管理后台"到"坐镇金銮殿"的沉浸式场景。
> 本文描述 `frontend/src/` 的设计：场景化组件树、SSE 实时流、状态管理。

## 技术栈

- React 19 + TypeScript（verbatimModuleSyntax：`import type` 严格）
- Vite 8（@tailwindcss/vite，Tailwind v4 免 config）
- TanStack Query（服务端状态 + 缓存失效）
- react-router-dom（场景路由）
- SSE（EventSource，实时事件流）
- **零 UI 依赖、零图片素材依赖**（纯 CSS/SVG，离线可跑）

## 组件树

```
App (路由)
└── Layout (世界壳：顶栏导航 + 场景舞台)
    ├── 金銮殿 ThroneHall          ← / （主场景）
    │   ├── ChancellorArrival      丞相进殿呈奏动画
    │   ├── CourtProgressPanel     政事进度面板
    │   └── 奏匣抽屉 + 奏折卷轴
    ├── 御史台 CensoratePage        ← /censorate（移驾）
    ├── 百官名册 PostsPage          ← /posts（翻阅）
    └── 拟旨下谕 EdictsPage         ← /edicts（御笔）
```

**路由即场景**：`/` 是金銮殿主场景，其他页面是"移驾/翻阅/御笔"的副场景。
Layout 的 `main key={pathname}` 触发场景切换动画（sceneEnter）。

## 数据层（api.ts）

类型化 API client，对接后端契约 7 组端点：

```typescript
api = {
  listMemorials(), verdictMemorial(id, value, comment),
  listEdicts(), getEdict(id), getEdictProgress(id), createEdict(form),
  listImpeachments(), verdictImpeachment(id, value),
  listPosts(), appointPost(id, agent),
  getEvents(params),
}
```

**关键设计**：
- 单例 client，所有组件共享
- 类型与后端契约对齐（Memorial/Edict/Post/Impeachment/EventRecord/EdictProgress）
- 可选字段优雅降级（`m.from_post_title ?? m.from_post`）

## SSE 实时流（useEventStream）

```typescript
// 事件 → 查询失效（react-query 自动重取）
const EVENT_QUERY_MAP = {
  edict: ["edicts"],
  memorial: ["memorials"],        // 新奏折 → 丞相进殿动画触发
  memorial_verdict: ["memorials"],
  impeachment: ["impeachments"],
  post_status: ["posts"],
};
```

**流程**：
1. EventSource 连接 `/api/events/stream`
2. 收到事件 → 对应 queryKey 失效 → react-query 重取
3. `memorial` 事件 → ThroneHall 检测新奏折（knownIds 对比）
   → 触发丞相进殿动画（stage: idle→arriving→presented→departing）

## 金銮殿场景（ThroneHall）

**核心状态机**（呈奏动画）：

```
idle ──新奏折到达──→ arriving（丞相进殿，4s）
arriving ──超时/跳过──→ presented（奏折已呈御前，可批红）
presented ──批红──→ departing（丞相谢恩退下，1.35s）
departing ──超时──→ idle
```

**交互元素**：
- 御案奏匣：点击打开抽屉，列出全部奏折（未批高亮 + 朱批状态）
- 奏折卷轴：展开（scaleX 动画）→ 正文 → 批红按钮 → 合上
- 政事进度面板：轮询 `/api/edicts/{id}/progress`（3s），
  进度条 + 子任务清单 + 三阶段文案
- 移驾令牌：御史台 / 百官名册 / 拟旨下谕

**场景视觉**（纯 CSS/SVG）：
- 背景：真实宫殿图 + 暖光渐变叠加（解决"太暗"）
- 殿柱/匾额/香炉/烛火：CSS 装饰层
- 丞相剪影：SVG（幞头+朝服），keyframes 多关键帧进殿
- 飞奏折：抛物线动画 + 落案展开

## 副场景

| 场景 | 视觉 | 功能 |
|---|---|---|
| 御史台 | 案卷库（木架 + 卷宗立牌） | 弹劾案卷、裁决（朱批准奏/驳回） |
| 百官名册 | 典籍册页（双页 + 书脊） | 官牌、人格画像卡片、空缺任命 |
| 拟旨下谕 | 圣旨卷轴（表单拟旨） | 结构化上谕表单、玉玺落下动画、历史圣旨 |

## 状态管理策略

- **服务端状态**：TanStack Query（缓存、失效、轮询）
- **UI 状态**：useState/useRef（选中奏折、动画 stage、抽屉开关）
- **全局共享**：QueryClient 单例 + queryKey 失效驱动

**无 Redux/Zustand**——状态量小且局部，YAGNI。

## 与后端的交互模式

```
前端                               后端
─────────────────────────────────────────────
mount → useQuery 拉初始数据   ←    REST
        EventSource 常连接    ←──  SSE 事件（实时）
        事件 → query 失效 → 重取 ←  REST
        下旨/批红/任命 → mutation → REST
        进度面板轮询 (3s)      →    REST /progress
```

## 真实教训

1. **奏折内容空白**：后端 list() 只返回部分字段，前端 content 为空
   → 后端 SELECT *（数据契约问题，前后端对齐）
2. **已批红奏折打不开**：御案只打开 pending[0] → 奏匣抽屉列出全部
3. **进度 0%**：后端 tracker 内存态重启丢失 → 存储兜底（edicts.status + 奏折推断）
4. **verbatimModuleSyntax**：类型导入必须 `import type`（tsc 强制）
5. **npm 慢/损坏**：Kylin 网络 npm 官方源卡 → npmmirror 镜像 + --no-audit
