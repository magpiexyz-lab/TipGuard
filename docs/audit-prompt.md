角色：你是一名技术文档审计员兼修复工程师，负责对 Assayer 平台的实施规格执行闭环审计-修复循环，直至 session-prompts.md 能完整产出另外两份文档所描述的产品。

## 文档体系（三层权威）

| 文档 | 职责 | 权威范围 |
|------|------|---------|
| `docs/assayer-product-design.md` | 产品架构与设计决策 | 能力、API、数据模型、技术栈 |
| `docs/ux-design.md` | 逐屏线框图与交互流程 | 页面、组件、用户旅程、响应式规则 |
| `docs/assayer-session-prompts.md` | 分步实施 prompt（Session 0-4） | **唯一可修改文件** |

权威性裁决规则（修复时使用）：
- 架构、能力、技术栈、漏斗定义 → 以 product-design.md 为准
- 页面名称、屏幕布局、交互流程、UI 元素 → 以 ux-design.md 为准
- 两份权威文档自身矛盾 → 以 ux-design.md 为准

## 核心约束

1. **唯一修改目标**：只能修改 `docs/assayer-session-prompts.md`。如果 gap 的根因在 mvp-template 或其他文件，正确做法是在 session-prompts.md 中创建一个新 prompt 步骤来执行该修改——而非直接修改源文件。
2. **完整性标准**：按顺序执行 session-prompts.md 中所有 prompt 后，产出必须 100% 覆盖 product-design.md 的每个 API 端点、数据模型、后台任务，以及 ux-design.md 的每个页面、组件、交互流程。
3. **无遗漏验证**：每轮审计必须逐项检查，不可依赖上一轮记忆（文件已被修改）。

## 执行流程

循环最多 **10 轮**，或 gap 归零时提前终止。

**关键：每轮循环开始时，必须先用 Read 工具读取 `docs/audit-prompt.md` 恢复完整指令，再执行阶段一。这是因为 /compact 会压缩上下文，直接依赖记忆会丢失格式和规则细节。**

### 阶段一：审计

1. 用 Read 工具完整读取三份文件（不要依赖上一轮记忆——文件已被修改）
2. 使用 extended thinking 深度分析以下三个维度：

| 维度 | 检查内容 | 常见漏点 |
|------|---------|---------|
| 完整性 | product-design.md 和 ux-design.md 中每个功能/页面/流程，在 session-prompts.md 中是否有对应实施步骤 | 新增的 API 端点、Cron Job、Webhook 处理器、数据库表/列、UI 组件 |
| 一致性 | 同一概念（漏斗维度、页面名称、技术栈、阈值、用户流程、枚举值）跨文档细节是否完全吻合 | 数值、命名、枚举顺序、状态机转换的微妙差异 |
| 可实施性 | 按 session-prompts.md 执行后，产出是否完整实现另外两份文档描述的产品（无隐式依赖、无遗漏配置、无顺序错误） | 环境变量、第三方 API 配置、数据库迁移顺序 |

3. 按以下格式输出每条发现（按严重度降序排列）：

```
### R{轮次}-G{序号} [{严重度: Critical/High/Medium/Low}] {一句话标题}

- **类别**：缺失 | 矛盾 | 定义不充分
- **涉及文档**：{文档名列表}
- **定位**：
  - `product-design.md` L{行号} / §{章节}
  - `ux-design.md` L{行号} / §{章节}
  - `session-prompts.md` L{行号} / §{章节}
- **预期**（引用权威文档原文）：{...}
- **实际**：{session-prompts.md 写了什么 / 未提及}
```

4. 如果发现零 Gap → 声明 ✅ 三份文档完全对齐，跳过阶段二，进入最终总结

### 阶段二：修复

对每个 Gap，在 session-prompts.md 中执行精确修复：
- 缺失 → 在正确的 Session 和步骤位置插入新 prompt 或扩展现有步骤
- 矛盾 → 修正 session-prompts.md 使其与权威文档对齐
- 定义不充分 → 补充具体实施细节（代码片段、SQL、API 签名等）
- 需要修改 mvp-template → 在 session-prompts.md 中添加一个新 prompt 步骤，指示执行该修改

修复后，输出本轮修改摘要表：

| Gap ID | 修复方式 | 修改位置（Session/步骤） |
|--------|---------|----------------------|

### 轮间操作

每轮结束后执行 `/compact`，然后开始下一轮。

### 最终总结（循环结束后）

输出：
1. 总轮次数和每轮 gap 数量趋势（如 R1:12 → R2:5 → R3:1 → R4:0）
2. 累计修复的 gap 总数，按类别分布
3. 当前 session-prompts.md 的覆盖率评估（相对于另外两份文档）
4. 如有残留风险（无法通过修改 session-prompts.md 解决的问题），明确列出
