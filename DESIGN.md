# AI Chat Widget — 设计规范

> 从 `frontend/ai-chat.tsx` 反向提取，版本 2026-07-10。此规范描述 React 组件；独立静态网站版本见 `frontend/standalone/ai-rag-chat.js`。

---

## 1. 组件层次

```
AiChat (MotionConfig)
├── FAB 按钮            ← 折叠态，右下角浮动
└── 聊天面板            ← 展开态
    ├── Header          ← 标题 + 操作按钮
    ├── Content         ← 聊天视图 / 历史视图
    │   ├── 空状态
    │   ├── ActivityRow (用户消息 / AI回复 / 错误)
    │   ├── ThinkingRow
    │   └── FollowUps
    └── Input Area      ← textarea + 发送按钮
```

---

## 2. 布局 & 尺寸

| 元素 | 属性 | 值 |
|------|------|-----|
| FAB 按钮 | 高度 | 44px (`h-11`) |
| FAB 按钮 | 内边距 | 左右 14px (`px-3.5`) |
| 聊天面板 (移动端) | 高度 | 85dvh |
| 聊天面板 (移动端) | 宽度 | 100vw, 顶部圆角 |
| 聊天面板 (桌面端) | 高度 | 512px (`h-[32rem]`), 最大 80vh |
| 聊天面板 (桌面端) | 宽度 | 384px (`w-[24rem]`), 最大 `calc(100vw - 2.5rem)` |
| 聊天面板 | 定位 | `fixed`, 桌面端 `absolute` 在右下角 |
| 聊天面板 | transform origin | `bottom right` |
| Header | 高度 | 56px (`h-14`) |
| Header | 内边距 | 左 14px, 右 8px |
| Header 按钮 | 尺寸 | 44px × 44px (`h-11 w-11`) |
| Header 按钮间距 | 间距 | 4px (`gap-1`) |
| 对话内容区 | 内边距 | 14px (`px-3.5 py-3.5`) |
| 对话内容区 | 间距 | 14px (`gap-3.5`) |
| 输入框容器 | 外边距 | 左右 12px, 底部 12px |
| 输入框 | 内边距 | 12px 10px (`px-3 py-2.5`) |
| 发送按钮 | 尺寸 | 44px × 44px (`h-11 w-11`) |
| textarea | 最大高度 | 96px (`max-h-24`) |
| 用户消息气泡 | 最大宽度 | 85% |
| 历史视图 | 内边距 | 6px 6px (`px-1.5 py-2`) |

---

## 3. 颜色

### 明色模式

| 用途 | Token | 值 |
|------|-------|-----|
| 面板/按钮背景 | `bg-white` | `#ffffff` |
| 面板背景 (带透明度) | `bg-white/95` | `rgba(255,255,255,0.95)` |
| 输入区背景 | `bg-neutral-50` | `#fafafa` |
| 用户气泡背景 | `bg-neutral-100` | `#f5f5f5` |
| 发送按钮 (激活) | `bg-neutral-900` | `#171717` |
| 发送按钮 (禁用) | `bg-neutral-100` | `#f5f5f5` |
| 面板边框 | `ring-neutral-200` | `#e5e5e5` |
| 头部/对话分隔线 | `border-neutral-200` | `#e5e5e5` |
| 建议按钮边框 | `border-neutral-200` | `#e5e5e5` |
| 主文字 | `text-neutral-900` | `#171717` |
| 正文 (AI回复) | `text-neutral-700` | `#404040` |
| 次要文字 (建议按钮) | `text-neutral-700` | `#404040` |
| 提示文字 (占位符) | `text-neutral-400` | `#a3a3a3` |
| 辅助文字 (空状态) | `text-neutral-500` | `#737373` |
| 副标题/时间 | `text-neutral-400` | `#a3a3a3` |
| 错误信息 | `text-red-500` | `#ef4444` |
| 发送按钮文字 (激活) | `text-white` | `#ffffff` |
| 发送按钮文字 (禁用) | `text-neutral-400` | `#a3a3a3` |
| 空状态图标 | `text-neutral-300` | `#d4d4d4` |
| Follow-ups 标签 | `text-neutral-400` | `#a3a3a3` |
| Copy 按钮默认 | `text-neutral-500` | `#737373` |
| Copy 按钮 Hover | `text-neutral-700` | `#404040` |

### 暗色模式 (`dark:`)

| 用途 | Token | 值 |
|------|-------|-----|
| 面板/按钮背景 | `bg-neutral-950/95` | `rgba(10,10,10,0.95)` |
| 输入区背景 | `bg-neutral-800` | `#262626` |
| 用户气泡背景 | `bg-neutral-800` | `#262626` |
| 发送按钮 (激活) | `bg-white` | `#ffffff` |
| 发送按钮 (禁用) | `bg-neutral-700` | `#404040` |
| 面板边框 | `ring-neutral-800` | `#262626` |
| 分隔线 | `border-neutral-800` | `#262626` |
| 建议按钮边框 | `border-neutral-700` | `#404040` |
| 主文字 | `text-neutral-100` | `#f5f5f5` |
| 正文 | `text-neutral-300` | `#d4d4d4` |
| 建议按钮文字 | `text-neutral-300` | `#d4d4d4` |
| 提示文字 | `text-neutral-500` | `#737373` |
| 副标题/时间 | `text-neutral-400` | `#a3a3a3` |
| 发送按钮文字 (激活) | `text-neutral-900` | `#171717` |
| 发送按钮文字 (禁用) | `text-neutral-400` | `#a3a3a3` |
| 空状态图标 | `text-neutral-700` | `#404040` |
| Hover 背景 | `hover:bg-neutral-800` | `#262626` |

---

## 4. 圆角

| 元素 | 值 | Tailwind |
|------|-----|----------|
| 聊天面板 | 16px | `rounded-2xl` |
| FAB 按钮 | 10px | `rounded-[10px]` |
| 输入框容器 | 11px | `rounded-[11px]` |
| 用户消息气泡 | 12px | `rounded-[12px]` |
| 历史列表项 Hover | 8px | `rounded-lg` |
| 历史列表项 | 8px | `rounded-lg` |
| Follow-up 按钮 | 8px | `rounded-lg` |
| Header 按钮 | 6px | `rounded-md` |
| 建议问题按钮 | full | `rounded-full` |
| 发送按钮 | full | `rounded-full` |
| Copy 按钮 | 6px | `rounded-md` |

---

## 5. 字体

| 元素 | 字号 | 字重 | 行高 |
|------|------|------|------|
| Header 标题 | 13px | 500 (medium) | — |
| 用户消息 | 13px | 400 | `leading-relaxed` (1.625) |
| AI 回复 | 13px | 400 | `leading-relaxed` (1.625) |
| 空状态提示 | 13px | 400 | `leading-relaxed` (1.625) |
| 输入框文字 | 13px | 400 | `leading-relaxed` (1.625) |
| FAB 标签 | 13px | 500 (medium) | — |
| 建议按钮 | 12px | 400 | — |
| 历史列表标题 | 13px | 400 | — |
| 历史列表时间 | 12px | 400 | — |
| 分组标签 (Today/Yesterday) | 11px | 600 (semibold) | — |
| Follow-ups 标签 | 11px | 500 (medium) | — |
| Follow-ups 内容 | 13px | 400 | — |
| Copy 按钮文字 | 11.5px | 400 | — |
| 整体字体家族 | `font-sans` | — | — |

---

## 6. 间距系统

| 场景 | 值 | Tailwind |
|------|-----|----------|
| FAB 距右下角 | 20px | `bottom-5 right-5` |
| Header 左内边距 | 14px | `pl-3.5` |
| Header 右内边距 | 8px | `pr-2` |
| Header 按钮间距 | 4px | `gap-1` |
| 对话消息间距 | 14px | `gap-3.5` |
| 对话区内边距 | 14px | `px-3.5 py-3.5` |
| 输入框水平外边距 | 12px | `px-3` |
| 输入框底部外边距 | 12px | `pb-3 / sm:pb-3` |
| 输入框内边距 | 12px × 10px | `px-3 py-2.5` |
| 发送按钮上边距 | 6px | `mt-1.5` |
| Follow-ups 上边距 | 2px | `mt-0.5` |
| Follow-ups 分隔线上边距 | 10px | `pt-2.5` |
| Follow-ups 分隔线下边距 | 2px | `mb-0.5` |
| Follow-ups 条目内边距 | 6px × 8px | `py-1.5 px-2` |
| 历史视图内边距 | 6px | `px-1.5 py-2` |
| 历史分组间距 | 6px | `mb-1.5` |
| 历史分组标签内边距 | 4px × 10px | `py-1 px-2.5` |
| 空状态间距 | 16px | `gap-4` |
| 建议按钮间距 | 6px | `gap-1.5` |
| Copy 按钮内边距 | 0 × 8px，最小高度 44px | `min-h-11 px-2` |
| Copy 按钮与回复间距 | 6px | `mt-1.5` |
| Thinking 点间距 | 6px | `gap-1.5` |

---

## 7. 动画

### FAB 按钮

| 属性 | 值 |
|------|-----|
| 入场 | spring, stiffness: 460, damping: 30 |
| 退场 | opacity 0, scale 0.9 |
| Hover | `hover:bg-neutral-50`, dark:`hover:bg-neutral-800` |
| Active | `active:scale-[0.96]` |

### 聊天面板

| 属性 | 值 |
|------|-----|
| 打开 | opacity 0→1, scale 0.96→1, y 12→0, duration 0.32s |
| 打开缓动 | `[0.23, 1, 0.32, 1]` (ease out strong) |
| 关闭 | opacity 1→0, scale 1→0.97, y 0→8, duration 0.16s |
| 关闭缓动 | `[0.23, 1, 0.32, 1]` |

### 消息入场

| 属性 | 值 |
|------|-----|
| 用户消息 | spring, stiffness: 420, damping: 32, from y 6 opacity 0 |
| AI 回复 | spring, stiffness: 420, damping: 32, from y 6 opacity 0 |
| 错误消息 | 无动画，静态显示 |

### 流式光标

| 属性 | 值 |
|------|-----|
| 动画 | opacity [1,1,0,0], duration 0.9s, infinite, linear |
| 尺寸 | 2px × 1.05em, 上移 2px |

### Thinking 加载点

| 属性 | 值 |
|------|-----|
| 点数 | 3 |
| 尺寸 | 6px × 6px (`h-1.5 w-1.5`) |
| 动画 | y [0, -4, 0], opacity [0.4, 1, 0.4], duration 1s, easeInOut |
| 延迟 | 0s, 0.15s, 0.3s |
| 颜色 | `bg-neutral-400` |

### Follow-ups

| 属性 | 值 |
|------|-----|
| 容器入场 | opacity 0→1, duration 0.25s |
| 条目入场 | spring, delay: i×0.05s, stiffness: 460, damping: 34 |
| 条目 Hover | `hover:bg-neutral-100`, dark:`hover:bg-neutral-800` |

### Copy 按钮

| 属性 | 值 |
|------|-----|
| 图标切换 | spring, duration 0.3s, bounce: 0 |
| 复制成功 | scale 0.25→1, opacity 0→1 + blur(4px)→0 |
| 显示复本 | 1400ms 后自动恢复 |
| 可见性 | 始终可见，键盘与触屏可发现 |

---

## 8. 交互状态

| 元素 | 状态 | 表现 |
|------|------|------|
| FAB | Hover | 背景变 `neutral-50`, dark:`neutral-800` |
| FAB | Active | scale 0.96 |
| FAB | Focus | `ring-2 ring-neutral-400` |
| 头部按钮 | Hover | 背景 `neutral-100` + 文字 `neutral-700`, dark: 背景 `neutral-800` + 文字 `neutral-300` |
| 头部按钮 | Active (历史) | 背景 `neutral-100` + 文字 `neutral-900` |
| 头部按钮 | Focus | `ring-2 ring-neutral-400` |
| 建议按钮 | Hover | 背景 `neutral-100` |
| 建议按钮 | Active | scale 0.96 |
| 建议按钮 | Focus | `ring-2 ring-neutral-400` |
| 历史列表 | Hover | 背景 `neutral-100` |
| 输入框 | Focus | 边框变 `neutral-300`, dark:`neutral-600` |
| 发送按钮 | 有内容 | 黑底白字, `hover:opacity-90` |
| 发送按钮 | 无内容/加载 | 浅灰底灰字, `bg-neutral-100 text-neutral-400` |
| 发送按钮 | Active | scale 0.96 |
| 发送按钮 | Focus | `ring-2 ring-neutral-400` |
| Follow-ups | Hover | 背景 `neutral-100`, dark:`neutral-800` |
| Copy | Hover | 背景 `neutral-100`, 文字 `neutral-700` |

---

## 9. 特殊效果

| 效果 | 用途 | 值 |
|------|------|-----|
| 毛玻璃 | 面板背景 | `backdrop-blur-xl` |
| 阴影 | 面板 | `shadow-2xl` |
| 阴影 | FAB | `shadow-lg` |
| 面板边框 | 面板外轮廓 | `ring-1 ring-neutral-200` |
| 安全区域 | 移动端底部 | `pb-[calc(0.75rem+env(safe-area-inset-bottom))]` |

---

## 10. 行为约束

| 约束 | 值 |
|------|-----|
| 输入最大字符 | 前后端均限制 4000 字符，输入框显示计数 |
| 历史记录轮数 | 后端限制 20 轮（40 条消息）；React 组件只保留本次访问的内存记录 |
| 会话标题截断 | 38 字符, 去除多余空白 |
| textarea 自动增高 | 每次输入后重算高度, 最大 96px |
| 发送快捷键 | Enter (非 Shift+Enter) |
| 流式回复中断 | 关闭面板、新建对话或 Stop 按钮会取消请求，并结束流式光标 |
| 客户端渲染 | `useEffect` 确保仅客户端挂载 |
| 相对时间显示 | just now (<60s) / Xm (<1h) / Xh (<24h) / Xd |
| 建议问题获取 | AI 回复完成后异步请求, 取前 3 条 |

---

## 11. 可访问性与可用性

- 面板使用 `role="dialog"`、`aria-modal`，打开后聚焦输入框；Escape 关闭并归还焦点。
- Tab 键在面板内循环；所有主要操作最小触控尺寸为 44px。
- 对话区使用语义化日志/状态/错误提示，加载状态可由屏幕阅读器获知。
- 仅当读者靠近底部时跟随流式输出；否则显示“Jump to latest”按钮。
- 复制操作始终可见；中断或网络错误会停止流式光标并保留已生成内容。

---

## 12. 子组件 props

### AiChat (根组件)

| Prop | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `apiBase` | string | `""` | 后端 API 基础 URL |
| `label` | string | `"Ask me anything"` | FAB 按钮文字 |
| `suggestions` | string[] | 3 条默认问题 | 空状态建议问题 |
| `emptyMessage` | string | `"Ask me about my work..."` | 空状态提示语 |
| `strings` | `Partial<AiChatStrings>` | 英文默认文案 | 固定 UI 文案、相对时间和计数的本地化 |

### 默认建议问题

```ts
[
  "What do you work on?",
  "Tell me about your experience",
  "What's your approach to your work?",
]
```

---

## 13. 响应式断点

| 断点 | 尺寸 | 行为 |
|------|------|------|
| Mobile (默认) | < 640px | 面板从底部弹出, 全宽, 85dvh 高, 顶部圆角 |
| Desktop (`sm:`) | >= 640px | 面板在右下角固定位置, 384×512px, 全圆角 |
| 安全区域 | — | 底部额外 `env(safe-area-inset-bottom)` 适配刘海屏 |

---

## 14. 依赖

| 包 | 版本要求 | 用途 |
|----|---------|------|
| `framer-motion` | — | 动画引擎 |
| `react` | 18+ | 运行时 |
| Tailwind CSS | — | 样式系统 |
