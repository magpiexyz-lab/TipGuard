# Assayer Portfolio Distribution：第一性原理分析与世界冠军 UX 设计

> 基于 4 个 Agent 团队的并行研究 + Assayer 全部设计文档的深度分析

---

## Part 1：第一性原理分析——该不该做？

### 1.1 从 Assayer 的核心价值出发

Assayer 是一台 **判决机器（verdict machine）**：
- 输入：不确定的想法
- 输出：确定的判决（SCALE / KILL / PIVOT / REFINE）

**当用户有 N 个想法时，判决机器的价值是 N 倍。** 但当前 Assayer 对每个想法独立运行判决——它是 N 个平行判决机器，不是一个 **优先级排序引擎**。

### 1.2 当前设计的缺口

| 已有 | 缺失 |
|------|------|
| Lab 按状态分组（RUNNING/VERDICT/COMPLETED） | 按优先级排序（哪个最值得投入？） |
| 单实验内 Scorecard 四维度 | 跨实验统一排名分数 |
| 单实验内 "Best channel" | 跨实验渠道/预算优化 |
| Comparison 视图（Pro/Team） | 智能推荐"下一步该把钱给谁" |
| 单实验 [Pause All] [Adjust] | 跨实验一键再分配 |
| 单实验预算警报 | 组合级预算健康度 |

### 1.3 为什么应该做：三个第一性原理论证

**论证 1：定价模型已经鼓励组合策略。**

设计文档明确写道：
> "Makes quick L1 pitch tests cheap — encouraging the portfolio approach."

L1 只要 $10，Pro 给 3 creates/mo。这意味着典型 Pro 用户会同时跑 2-3 个实验。但当前 UX 没有帮助他们在这 2-3 个实验之间做资源决策——这是一个 **价值断裂**。

**论证 2：护城河延伸。**

设计文档定义护城河为：
```
Assayer: Idea → Code → Deploy → Distribute → Measure → Verdict
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

如果加上跨实验优化，护城河变为：
```
Assayer: Idea×N → Code → Deploy → Distribute → Measure → Verdict
                                   → Rank → Reallocate → Repeat
                                     ^^^^^^^^^^^^^^^^^^^^^^^^^
                                     竞争对手更不可能复制这段
```

没有任何竞品（Lovable、Replit、v0）做跨实验资源优化。这是 **唯一的蓝海功能**。

**论证 3：化学家类比的自然延伸。**

> "客户带来岩石样本，化验师运行测试，告诉你是不是金子。"

当客户带来 5 块岩石时，化验师不会只说"这块是金子，那块不是"。优秀的化验师会说：**"先测这块（信号最强），暂停那块（信号太弱），这块需要换个检测方法。你的检测预算应该这样分配。"**

这正是 Portfolio Distribution 的价值——Assayer 从 **单品化验师** 升级为 **矿场顾问**。

### 1.4 为什么不应该过度做

**风险 1：复杂度杀死 MVP。**

Assayer 自己还是 MVP。Session prompts 显示它尚未构建（所有 TODO）。加入复杂的组合优化会：
- 增加 Session 数量（至少 +2）
- 增加需要验证的 UX 路径
- 可能延迟发布

**风险 2：用户认知负荷。**

大多数早期用户只跑 1-2 个实验。如果 Lab 首屏就展示"组合分数"和"预算再分配"，会让简单场景变复杂。

**结论：分层交付。**

| 层级 | 功能 | 交付时机 | 目标用户 |
|------|------|---------|---------|
| **L0（基础）** | Lab 增强排序 + 一个数字（Assayer Score） | Assayer v1 | 所有用户 |
| **L1（智能推荐）** | AI 生成跨实验资源建议 | Assayer v1.1 | Pro 用户 |
| **L2（自动优化）** | Thompson Sampling 自动再分配 | Assayer v2 | Team 用户 |

---

## Part 2：世界冠军 UX 设计

### 2.1 设计公理（继承自 ux-design.md）

- **Axiom A：价值在承诺之前。** 组合视图的价值在用户开始第二个实验时自动出现。
- **Axiom B：过程即产品。** 让用户看到 AI 如何分析他们的组合并生成建议。
- **Axiom C：实验是故事。** 组合不是电子表格——它是一系列赌注的叙事。
- **新 Axiom D：一个数字回答一个问题。** 每个实验一个 Assayer Score，整个组合一个 Portfolio Health Score。

### 2.2 核心概念：Assayer Score 作为统一货币

每个实验卡片需要 **一个数字** 来表达"值不值得继续投入"。

当前 Lab 卡片显示的是 bottleneck ratio（如 `1.90x`）。但这不够——它只表示一个维度的健康度，不表示综合投资回报。

**Assayer Score** = 综合所有维度的单一数字，用于排名。

在 Lab 中显示为：

```
+---------------------+
| AI Invoice Tool     |
|  ★ 89              |  ← Assayer Score (0-100, 简化为单一数字)
|  Day 3/7  ON TRACK  |
|  4 ch · $62 · 502  |
|  L1 Pitch           |
+---------------------+
```

Score 0-100 的映射：
- 80-100：强信号，SCALE 候选
- 60-79：有希望，REFINE 方向
- 40-59：弱信号，需要关注
- 20-39：危险，PIVOT 或 KILL 考虑
- 0-19：无信号，应该 KILL

### 2.3 Lab 增强设计（L0 — Assayer v1）

现有 Lab 已经按状态分组（RUNNING/VERDICT READY/COMPLETED）。增强方向：**在 RUNNING 组内，按 Assayer Score 降序排列。**

```
+--------------------------------------------------------------+
|  Your Lab                                     [+ New Idea]   |
|                                                              |
|  RUNNING (3)                          sorted by Assayer Score|
|  +---------------------+  +---------------------+           |
|  | AI Invoice Tool  ★89|  | Task Manager     ★54|           |
|  |                     |  |                     |           |
|  | R 1.9x D 1.3x M .7x|  | R .9x D .6x M ---  |           |
|  | Day 3/7    ON TRACK |  | Day 5/14    LOW !   |           |
|  | 4 ch · $62 · 502 cl |  | 2 ch · $180 · 90 cl|           |
|  | L1 Pitch            |  | L2 Proto            |           |
|  +---------------------+  +---------------------+           |
|                                                              |
|  +---------------------+                                    |
|  | Crypto Widget    ★12|  ← 排名最低，视觉上退后            |
|  | R .4x D .3x M ---   |                                    |
|  | Day 10/14  DANGER   |                                    |
|  | 1 ch · $200 · 34 cl |                                    |
|  +---------------------+                                    |
|                                                              |
|  == AI INSIGHT ============================================= |
|  "AI Invoice Tool has the strongest signal (89). Consider    |
|   doubling its ad budget. Crypto Widget shows no demand      |
|   signal after 200 clicks — consider killing it to free      |
|   $280 for better-performing experiments."                   |
|  [Apply suggestions ->]                        [Dismiss]     |
|                                                              |
|  VERDICT READY (1)                                           |
|  ...                                                         |
+--------------------------------------------------------------+
```

**关键设计决策：**

1. **Assayer Score 在卡片右上角**——最显眼位置，一个数字。
2. **RUNNING 组按 Score 降序排列**——视觉传达优先级。
3. **卡片显示三维度压缩**：`R 1.9x D 1.3x M .7x`——比当前只显示 bottleneck ratio 更丰富，但仍然紧凑。
4. **AI Insight 卡片**——这是杀手功能。当用户有 2+ RUNNING 实验时，AI 自动生成跨实验建议。这不是功能——这是 Assayer 从化验师升级为顾问的 **核心表达**。
5. **[Apply suggestions]**——一键执行 AI 建议（暂停差的，加预算给好的）。

### 2.4 AI Insight 系统（L1 — Assayer v1.1）

AI Insight 是 **Portfolio 版的 /iterate**。它读取所有 RUNNING 实验的 iterate-manifest.json，生成跨实验建议。

**触发条件：**
- 用户有 2+ RUNNING 实验
- 至少一个实验有 30+ visits（有数据可比）
- 每 24 小时自动更新，或用户点击 [Refresh Insight]

**生成逻辑（服务端，Anthropic API）：**

```
输入：
  - 所有 RUNNING 实验的 iterate-manifest.json
  - 所有 RUNNING 实验的 ads.yaml（spend, channels, thresholds）
  - PostHog 聚合数据（per-experiment funnel_scores）

输出：
  {
    "portfolio_health": 72,        // 0-100
    "top_experiment": "ai-invoice", // Assayer Score 最高
    "recommendations": [
      {
        "type": "scale",
        "experiment": "ai-invoice",
        "action": "Increase Google Ads budget from $120 to $240",
        "reason": "Strongest signal (89), Google Ads CPA $0.17"
      },
      {
        "type": "kill",
        "experiment": "crypto-widget",
        "action": "Stop ads, run /retro",
        "reason": "0 activations after $200 spend, 34 clicks"
      },
      {
        "type": "rebalance",
        "from": "crypto-widget",
        "to": "ai-invoice",
        "amount_cents": 28000,
        "reason": "Freed budget from killed experiment"
      }
    ],
    "next_check": "2026-03-19T00:00:00Z"
  }
```

### 2.5 Comparison 视图增强

现有 Comparison 视图已经很好。增加 Assayer Score 列和 AI 推荐行：

```
+--------------------------------------------------------------+
|  Compare Experiments                    [Export CSV]          |
|                                                              |
|              AI Invoice  Task Mgr    Crypto Widget           |
|  Score        ★ 89       ★ 54        ★ 12                   |
|  REACH        1.90x ok    0.89x !     0.41x x               |
|  DEMAND       1.34x ok    0.55x !     0.32x x               |
|  ACTIVATE     -- (L1)     1.05x ok    -- (L1)               |
|  MONETIZE     0.65x !     -- (L2)     -- (L1)               |
|  RETAIN       -- (L1)     -- (L2)     -- (L1)               |
|  -----------------------------------------------------------  |
|  Verdict      on track    behind      danger                 |
|  Confidence   reliable    directional insufficient           |
|  Ad Spend     $62         $180        $200                   |
|  CPA          $7.75       $60         --                     |
|  Best Channel Google Ads  Twitter     --                     |
|                                                              |
|  == AI RECOMMENDATION ==================================== = |
|                                                              |
|     ★ AI Invoice Tool is your strongest bet.                 |
|                                                              |
|     1. Kill Crypto Widget → save $280 remaining budget       |
|     2. Move saved budget to AI Invoice → Google Ads          |
|     3. Give Task Manager 5 more days before deciding         |
|                                                              |
|     [Apply All ->]    [Apply #1 only]    [Dismiss]           |
|                                                              |
+--------------------------------------------------------------+
```

### 2.6 Budget Allocation 视图（L2 — Assayer v2，Team plan）

这是最高级的功能——可视化预算分配和一键再分配。

**入口**：Lab 页面顶部新增 [Budget] 标签（与现有 Lab 视图平级）

```
+--------------------------------------------------------------+
|  Your Lab    [Experiments]  [Budget]              [+ New Idea]|
|                                                              |
|  PORTFOLIO BUDGET                                            |
|                                                              |
|  Total allocated: $442 / $500          Remaining: $58        |
|  =========================================......             |
|                                                              |
|  +-- EXPERIMENT ----+-- SPENT --+-- REMAINING --+-- SCORE --+|
|  | AI Invoice Tool  |  $62      |  $138         |  ★ 89    ||
|  | ################ |           |               |  SCALE ↑  ||
|  +------------------+-----------+---------------+-----------+|
|  | Task Manager     |  $180     |  $120         |  ★ 54    ||
|  | ########........ |           |               |  REFINE ~ ||
|  +------------------+-----------+---------------+-----------+|
|  | Crypto Widget    |  $200     |  $0 (spent)   |  ★ 12    ||
|  | ################ |           |               |  KILL x   ||
|  +------------------+-----------+---------------+-----------+|
|                                                              |
|  == AI BUDGET OPTIMIZER ==================================== |
|                                                              |
|  Based on Assayer Scores and channel performance:            |
|                                                              |
|  CURRENT              →    RECOMMENDED                       |
|  AI Invoice:  $200         AI Invoice:  $380 (+$180)         |
|  Task Mgr:    $300         Task Mgr:    $120 (-$180)         |
|  Crypto:      $200         Crypto:      $0   (kill)          |
|                                                              |
|  Reasoning:                                                  |
|  · AI Invoice CPA ($7.75) is 8x better than Task Mgr ($60)  |
|  · Crypto has zero activations — continuing spend is waste   |
|  · Task Mgr gets minimum budget to gather more signal        |
|                                                              |
|  [Apply Rebalance ->]                          [Customize]   |
|                                                              |
+--------------------------------------------------------------+
```

**[Customize] 展开为滑块界面：**

```
|  CUSTOMIZE ALLOCATION                                        |
|                                                              |
|  Total: $500                                                 |
|                                                              |
|  AI Invoice Tool  ★89                                        |
|  [$380]  ========================================......  76% |
|                                                              |
|  Task Manager     ★54                                        |
|  [$120]  ============..................................  24% |
|                                                              |
|  Crypto Widget    ★12  [PAUSED]                              |
|  [$0]    ...............................................  0%  |
|                                                              |
|  [Apply ->]                                    [Reset]       |
|                                                              |
```

### 2.7 移动端设计（Glance Mode）

Lab 在移动端需要特别优化——用户站着看手机时只想知道"哪个实验需要我关注？"

```
+------------------------------------------+
|  [Assayer]                     [Avatar]   |
+------------------------------------------+
|                                          |
|  Your Lab              Portfolio: ★ 72   |
|                                          |
|  NEEDS ATTENTION (1)                     |
|  +--------------------------------------+|
|  | Crypto Widget         ★ 12  DANGER  ||
|  | 0 activations · $200 spent          ||
|  | AI recommends: Kill                  ||
|  | [Kill & Free Budget] [View ->]      ||
|  +--------------------------------------+|
|                                          |
|  ON TRACK (2)                            |
|  +--------------------------------------+|
|  | AI Invoice Tool      ★ 89  SCALE    ||
|  | 8 activations · $62 spent           ||
|  +--------------------------------------+|
|  +--------------------------------------+|
|  | Task Manager          ★ 54  REFINE  ||
|  | 3 activations · $180 spent          ||
|  +--------------------------------------+|
|                                          |
+------------------------------------------+
|   Lab        New        Settings         |
+------------------------------------------+
```

**移动端设计决策：**

1. **Portfolio Health Score** 在顶部——一个数字总结所有实验。
2. **"NEEDS ATTENTION" 优先**——把需要行动的实验放最上面（不是按 Score 排序，而是按紧急度）。
3. **内联行动按钮**——[Kill & Free Budget] 直接在卡片上，不需要进入详情。
4. **ON TRACK 实验压缩显示**——不需要行动的实验只显示 Score 和一行摘要。

### 2.8 通知增强

当 AI Insight 生成跨实验建议时，发送 Portfolio Notification：

```
+--------------------------------------------------------------+
|                                                              |
|  Assayer                                                     |
|                                                              |
|  Portfolio Update — 3 experiments                            |
|                                                              |
|  ★ 72 Portfolio Health                                       |
|                                                              |
|  AI Invoice Tool  ★89  ↑  SCALE signal strengthening        |
|  Task Manager     ★54  →  Holding, needs 5 more days        |
|  Crypto Widget    ★12  ↓  Recommend: Kill                    |
|                                                              |
|  Suggested action:                                           |
|  Kill Crypto Widget → free $280 → add to AI Invoice          |
|                                                              |
|  [Open Lab ->]                                               |
|                                                              |
+--------------------------------------------------------------+
```

---

## Part 3：技术实现方案

### 3.1 数据模型扩展

在现有 Supabase schema 上新增：

```sql
-- Portfolio-level scores (computed, cached)
ALTER TABLE experiments ADD COLUMN assayer_score INTEGER;  -- 0-100
ALTER TABLE experiments ADD COLUMN score_updated_at TIMESTAMPTZ;

-- Portfolio insights (AI-generated)
CREATE TABLE portfolio_insights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users NOT NULL,
  insight_json JSONB NOT NULL,          -- recommendations array
  portfolio_health INTEGER NOT NULL,    -- 0-100
  created_at TIMESTAMPTZ DEFAULT now(),
  dismissed_at TIMESTAMPTZ             -- null if not dismissed
);

-- Budget allocation history
CREATE TABLE budget_allocations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users NOT NULL,
  allocation_json JSONB NOT NULL,       -- {experiment_id: amount_cents}
  source TEXT NOT NULL,                 -- 'ai_recommended' | 'user_custom'
  applied_at TIMESTAMPTZ DEFAULT now()
);
```

### 3.2 Assayer Score 计算（Vercel Cron，15min）

```typescript
function computeAssayerScore(experiment: Experiment): number {
  const manifest = experiment.iterate_manifest;
  if (!manifest) return 0;

  const scores = manifest.funnel_scores;
  const signal =
    0.30 * (scores.reach?.score ?? 0) +
    0.30 * (scores.demand?.score ?? 0) +
    0.20 * (scores.monetize?.score ?? 0) +
    0.10 * (scores.retain?.score ?? 0);
  // PMF and GROWTH not available at L0 — normalize to 90% base

  const confidence = sampleFactor(experiment.total_visits)
    * freshnessFactor(manifest.analyzed_at);

  const efficiency = experiment.activations > 0
    ? 1 / Math.max(experiment.total_spend / experiment.activations / BENCHMARK_CAC, 0.1)
    : 0.1;

  const risk = Math.max(
    (estimatedCostToProduct(experiment) - experiment.total_spend) / MAX_BUDGET, 0.1);

  const raw = (signal * confidence * efficiency) / risk;
  return Math.min(Math.round(raw), 100);  // cap at 100
}
```

### 3.3 AI Insight 生成（Vercel Cron，daily）

```typescript
// Triggered daily for users with 2+ RUNNING experiments
async function generatePortfolioInsight(userId: string) {
  const experiments = await getRunningExperiments(userId);
  if (experiments.length < 2) return;

  const context = experiments.map(e => ({
    name: e.name,
    score: e.assayer_score,
    funnel_scores: e.iterate_manifest?.funnel_scores,
    spend: e.total_spend_cents,
    activations: e.activations,
    best_channel: e.best_channel,
    days_elapsed: e.days_elapsed,
    days_total: e.duration_days,
  }));

  const insight = await anthropic.messages.create({
    model: 'claude-sonnet-4-6',  // Sonnet for cost efficiency
    messages: [{ role: 'user', content: PORTFOLIO_INSIGHT_PROMPT(context) }],
    // ... structured output schema
  });

  await supabase.from('portfolio_insights').insert({
    user_id: userId,
    insight_json: insight,
    portfolio_health: computePortfolioHealth(experiments),
  });
}
```

### 3.4 Session 追加

在现有 session prompts 中增加：

```
| Session | Status | Description |
|---------|--------|-------------|
| 7b | TODO | Portfolio: Assayer Score on Lab cards + AI Insight + Budget tab |
```

这作为 Session 7（Lab + Verdict + Compare + Settings）的子任务，不增加独立 session。

### 3.5 计费影响

| 功能 | 计费 | 理由 |
|------|------|------|
| Assayer Score 在 Lab | 免费 | 所有用户都应该看到排名 |
| AI Insight（文字建议） | Pro+ | 需要 AI 计算，Pro 功能 |
| [Apply suggestions] 一键执行 | Pro+ | 触发实际广告平台操作 |
| Budget 标签 + 滑块分配 | Team | 高级组合管理 |
| 自动再分配（Thompson Sampling） | Team | 最高级自动化 |

---

## Part 4：为什么这是世界冠军方案

### 4.1 与竞品对比

| 功能 | Assayer | Lovable | Replit | Optimizely | Google Ads |
|------|---------|---------|--------|------------|------------|
| 单实验构建 | ✅ | ✅ | ✅ | ❌ | ❌ |
| 单实验判决 | ✅ | ❌ | ❌ | ✅ | ❌ |
| 多实验排名 | ✅ (新) | ❌ | ❌ | 部分 | ❌ |
| 跨实验预算优化 | ✅ (新) | ❌ | ❌ | ❌ | 部分 (同账户) |
| AI 组合建议 | ✅ (新) | ❌ | ❌ | ❌ | ❌ |
| 一键预算再分配 | ✅ (新) | ❌ | ❌ | ❌ | ❌ |

### 4.2 差异化来源

1. **唯一的端到端组合优化**：从想法到预算分配到判决，没有竞品覆盖全链路。
2. **AI 顾问模式**：不只是数据展示——AI 主动告诉你"杀掉这个，加注那个"。
3. **一个数字（Assayer Score）**：Robinhood 化的实验组合管理，降低认知负荷。
4. **化学家→矿场顾问**：品牌隐喻的自然升级，不需要改变 narrative。

### 4.3 风险与缓解

| 风险 | 缓解 |
|------|------|
| 增加 Assayer 构建复杂度 | 分 L0/L1/L2 交付，L0 只是 Lab 排序 |
| 用户只有 1 个实验时无用 | 隐藏组合功能直到第 2 个实验，优雅降级 |
| AI Insight 不准确 | 标注为"建议"而非"命令"，用户总是有 [Dismiss] |
| 自动再分配出错 | L2 功能（Team only），需要人工审批 gate |

### 4.4 交付路线图

```
Assayer v1.0（首次发布）：
  ✅ Lab 卡片增加 Assayer Score
  ✅ RUNNING 组按 Score 排序
  ✅ Comparison 视图增加 Score 列

Assayer v1.1（发布后 2-4 周）：
  ✅ AI Insight 卡片（跨实验建议）
  ✅ [Apply suggestions] 一键执行
  ✅ Portfolio Notification（邮件）
  ✅ 移动端优化（NEEDS ATTENTION 优先排序）

Assayer v2.0（产品-市场契合后）：
  ✅ Budget 标签 + 滑块分配
  ✅ Thompson Sampling 自动再分配
  ✅ Portfolio Health Score
  ✅ 历史分配追踪 + 回溯分析
```

---

## 附录：信息架构更新

更新 ux-design.md 的 Information Architecture：

```
Lab (Your Lab) — UPDATED
  |-> Running (sorted by Assayer Score)     ← NEW
  |     |-> Per-experiment card with Score  ← NEW
  |     +-> AI Insight (when 2+ running)    ← NEW
  |-> Verdict Ready (needs attention)
  |-> Completed (historical verdicts)
  |-> Linked rounds (Round 1 → Round 2)
  |-> Pivot lineage (Original → Pivot)
  |-> [Budget] tab (Team plan)              ← NEW
  |     |-> Portfolio budget overview
  |     |-> AI Budget Optimizer
  |     +-> Custom allocation sliders
  +-> [+ New Idea]
```
