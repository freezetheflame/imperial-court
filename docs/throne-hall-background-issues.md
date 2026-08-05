# 金銮殿背景视觉问题记录（Background Visual Issues）

> 状态：问题记录 + 方案方向，**未实施**（2026-08-05）
> 背景：皇帝体验设计中"金銮殿场景"的美观问题。用户反馈当前背景由大量
> CSS 几何图形（三角形/圆形/梯形 clip-path）拼成，**丑陋、缺乏正式感**。
> 本文档记录问题根因与可行的重构方向，待具备图像生成能力后实施。

---

## 1. 问题诊断

### 1.1 现状（代码证据）

金銮殿背景（`.throne-hall`，frontend/src/index.css:37-41）是**纯 CSS 几何拼贴**：

| 元素 | 实现方式 | 观感问题 |
|---|---|---|
| 天花板 `.hall-ceiling` | `repeating-linear-gradient` + `clip-path: polygon(0 0,100% 0,87% 100%,13% 100%)` | 几何梯形，无质感 |
| 远门 `.distant-doors` | 两个 span + `perspective + rotateY` | 平面感强 |
| 殿柱 `.hall-columns` | `perspective(800px) rotateY` + 渐变圆柱 + `clip-path` 斗拱 | 假 3D，光影不真实 |
| 御道 `.imperial-way` | `clip-path: polygon(36% 0,64% 0,100% 100%,0 100%)` | 明显的三角形，最扎眼 |
| 丹陛 `.dais` | `clip-path: polygon(8% 0,92% 0,100% 100%,0 100%)` | 同上 |
| 香炉/烛火 | 小 div + 动画 | 细节粗糙 |

**根因**：CSS 几何体只能表达"像建筑的符号"，表达不了建筑的真实感与正式感。
透视（rotateY/perspective）是线性近似，真实建筑的纵深、光影、材质（木纹、漆面、
织物）都无法由渐变模拟。**这是路线问题，不是工作量问题**——再多加几何元素只会更乱。

### 1.2 讽刺的关键发现：其实已经有一张背景图，但被盖死了

`.throne-hall` 的 background 声明**包含** `url("./assets/hall-bg.jpg")`，
但它被两层高不透明渐变完全盖住：

```css
background:
  radial-gradient(ellipse at 50% 30%, #ffd9a066 0, transparent 55%),   /* 光晕 */
  linear-gradient(180deg, #3a1c0dcc 0%, #5a2c14aa 30%, ...),           /* ~80% 不透明 */
  url("./assets/hall-bg.jpg") center 30% / cover no-repeat,            /* 被上面盖死 */
  #2d1210;
```

即：**作者曾试图用真实图片做背景，但渐变层不透明度太高（cc/aa ≈ 80%），
照片几乎透不出来**，用户只能看到色块 + 几何体。修 CSS 让图片透出来，
比继续堆几何体有效得多。

---

## 2. 推荐重构方向（分层渲染）

> 原则：**背景图当主角，CSS 只做氛围，绝不用 CSS 做建筑。**

### 2.1 三层结构

```
┌─────────────────────────────────────────┐
│ L1 背景图（真实照片 / AI 生图）           │  ← 80% 的正式感来源
│   中心对称宝座构图，暗色调，16:9          │
├─────────────────────────────────────────┤
│ L2 氛围层（CSS 渐变/暗角，很轻）          │
│   顶部微暗 + 底部渐暗（保证 UI 可读）      │
│   边缘暗角（::after + box-shadow inset）  │
├─────────────────────────────────────────┤
│ L3 UI 层（现有：御案/奏折/按钮/动画）      │  ← 保持不变
└─────────────────────────────────────────┘
```

### 2.2 具体改动点（实施时）

1. **背景图**：
   - 首选：AI 生图（FAL_KEY 或 Nous Portal 配置后），prompt 见 §4
   - 备选：Wikimedia Commons 公有领域真实宫殿照片（已验证可下载，见 §3）
   - 要求：中心对称、宝座位于画面中上部、暗色调、横向 16:9
2. **`.throne-hall` 背景声明**：大幅降低渐变不透明度（cc/aa → 40-60%），
   让照片透出；底部保留渐暗保证按钮/文字可读
3. **新增 `.throne-hall::after` 暗角**：`box-shadow: inset 0 0 160px 40px #05020166`，
   pointer-events: none
4. **删除/弱化与照片重叠的几何元素**（照片里已有真实殿柱/丹陛/宝座，CSS 版是重复且丑）：
   - `.hall-columns`（照片有真实柱子）→ 删除
   - `.distant-doors`、`.imperial-way`、`.dais` → 删除
   - `.hall-ceiling` → 可删除或降为极暗渐变
   - `.candle`、`.incense-burner` → 可保留（氛围小元素，照片里没有）或删除
5. **保留**：匾额 `.plaque`（照片上方叠加，有"正大光明"正式感）、
   `.imperial-desk` 御案（前景，遮住照片底部，天然衔接）、
   奏折卷轴/丞相动画（L3 不变）

### 2.3 已做的验证（2026-08-05，已回滚）

曾做一次性实验（随后按用户要求回滚，仓库现为干净状态）：
- 用 Wikimedia 照片处理成 2560×1440 背景（16:9 裁切 + 压暗 45% + 高斯暗角），
  替换 hall-bg.jpg
- 降低渐变透明度 + 加 ::after 暗角
- 结论：**方向可行**——真实照片 + 轻氛围层视觉立即提升，几何体明显多余。
  但当前环境无 AI 生图能力，且照片（沈阳故宫崇政殿）风格与"金銮殿"设定有出入，
  故未保留，待正式素材再实施。

---

## 3. 已验证可用的真实照片素材（Wikimedia Commons，公有领域）

已下载验证（/tmp/hall-cand-02.jpg、/tmp/hall-cand-pic.jpg，原文件已保留在 /tmp）：

| 文件 | 尺寸 | 构图 | 亮度 |
|---|---|---|---|
| `2014 Manchu Forbidden City- Chongzheng Hall Dragon Throne 02.jpg` | 4752×3168 | 横向 | mean 104，较暗庄重 |
| `Throne Forbidden City pic.jpg` | 3072×2048 | 横向 | mean 129，偏暖金 |

两图均为"中心亮（宝座聚光）、边缘暗"构图，适合做背景。
完整系列：`2014 Manchu Forbidden City- Chongzheng Hall Dragon Throne 01~09.jpg`
（沈阳故宫崇政殿龙椅，搜 "Forbidden City throne hall" filetype:bitmap 可找到）。

注意：**这是沈阳故宫（崇政殿），不是北京太和殿**。若追求"金銮殿=太和殿"的
准确设定，需另找太和殿内部照片或 AI 生图。

---

## 4. AI 生图 Prompt 参考（待 FAL_KEY / Nous Portal 配置后使用）

```
中国古代皇宫金銮殿内部场景，从大殿中央视角望向深处的皇帝宝座。
金色雕龙宝座居中端坐于汉白玉台阶之上，背后是金漆屏风。
两侧朱红漆大柱对称排列延伸向画面深处，形成强烈透视纵深。
殿内光线昏暗庄重，顶部垂下宫灯，香炉青烟袅袅。
整体色调：深红、暗金、暖黄烛光，风格写实油画家底、大气磅礴、庄严肃穆。
空无一人，只有空荡荡的朝堂。
构图：中央对称，宝座位于画面中上部，下方留出大片空旷殿内地面（方便放置 UI 元素）。
适合作为网页游戏背景图，16:9 横构图。
```

---

## 5. 实施前置条件（阻塞项）

- [ ] **图像生成能力**：配置 FAL_KEY（`hermes model` / fal.ai 免费 key）或 Nous Portal billing；
      或用 §3 真实照片（无需生图，但风格是沈阳故宫）
- [ ] 决定素材路线：AI 生图（设定精准、风格统一）vs 真实照片（免费、真实但风格受限）
- [ ] 实施后 `npm run build` 验证 + 目视检查四个页面

## 6. 相关链接

- 设计权威：`docs/emperor-experience-design.md`（皇帝体验四闭环）
- 前端现状：`frontend/src/index.css`（.throne-hall 起）、`frontend/src/components/ThroneHall.tsx`
