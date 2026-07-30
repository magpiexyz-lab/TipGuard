# MVP 广告预算与 ROI 排名：实操 Playbook

> 第一性原理：MVP 广告的目的不是获取用户，而是购买信息。每一美元应该最大化你对"这个 MVP 是否值得继续"的确定性。

---

## 目录

1. [核心公式：Assayer Score](#1-核心公式assayer-score)
2. [三阶段预算模型](#2-三阶段预算模型phase-gated-budget)
3. [多 MVP 组合分配](#3-多-mvp-组合分配)
4. [渠道选择指南](#4-渠道选择指南)
5. [漏斗基准数据](#5-漏斗基准数据2025-2026)
6. [判决矩阵](#6-判决矩阵)
7. [Kill 标准](#7-kill-标准硬停止信号)
8. [实操流程](#8-实操流程与-mvp-template-集成)
9. [测量节奏](#9-测量节奏)
10. [高级方法](#10-高级方法)

---

## 1. 核心公式：Assayer Score

**用途**：对所有活跃 MVP 进行统一排名，决定广告预算和工程资源分配。

```
Assayer Score = (Signal × Confidence × Efficiency) / Risk
```

### 1.1 Signal（信号强度）

来自 `/iterate` 的 Validation Scorecard 四维度：

```
Signal = 0.25 × REACH + 0.25 × DEMAND + 0.15 × MONETIZE + 0.10 × RETAIN
       + 0.15 × PMF + 0.10 × GROWTH

每个维度 score = min(actual / threshold, 1.0) × 100
```

| 维度 | 数据来源 | 计算方式 |
|------|---------|---------|
| REACH | Ad CTR + 着陆页访问量 | `funnel.reach.threshold` vs 实际 |
| DEMAND | CTA 点击率 + 注册转化率 | `funnel.demand.threshold` vs 实际 |
| MONETIZE | 支付开始 + 完成率 | `funnel.monetize.threshold` vs 实际 |
| RETAIN | 回访 + 重复行为 | `funnel.retain.threshold` vs 实际 |
| PMF | Sean Ellis "very disappointed" % | <15%→0, 15-25%→25, 25-39%→50, 40-60%→80, >60%→100 |
| GROWTH | 周环比增长率 | <1%→10, 1-3%→30, 3-5%→50, 5-7%→75, >7%→100 |

> PMF 和 GROWTH 在 Phase 1 不可用——Phase 1 只用前四个维度（权重重新归一化）。

### 1.2 Confidence（置信度）

```
Confidence = sample_factor × freshness_factor

sample_factor:
  < 30 visits   → 0.3（insufficient data）
  30-100 visits  → 0.6（directional signal）
  100-500 visits → 0.8（reliable）
  500+ visits    → 1.0（high confidence）

freshness_factor:
  数据 < 3 天    → 1.0
  数据 3-7 天    → 0.9
  数据 7-14 天   → 0.7
  数据 > 14 天   → 0.5
```

### 1.3 Efficiency（效率）

```
CAC = total_ad_spend / activations
CAC_normalized = CAC / industry_benchmark_CAC

Efficiency = 1 / max(CAC_normalized, 0.1)

特殊情况：
  activations == 0 → Efficiency = 0.1
```

**行业基准 CAC 参考**：

| 类型 | 基准 CAC |
|------|---------|
| Consumer App (免费增值) | $20-100 |
| Consumer SaaS | $50-200 |
| SMB SaaS | $200-500 |
| E-commerce | $30-100 |
| Enterprise SaaS | $1,000-5,000 |

### 1.4 Risk（风险）

```
remaining_investment = estimated_cost_to_product - spent_so_far
Risk = remaining_investment / max_budget_per_mvp

估算 estimated_cost_to_product：
  Phase 1 中的 MVP → $800-2000（更多广告 + 4-8 周工程）
  Phase 2 中的 MVP → $300-800（优化广告 + 2-4 周工程）
  Phase 3 中的 MVP → $0-300（生产化工作）
```

### 1.5 排名示例

| MVP | Visits | Signups | Activations | Spend | Signal | Conf. | Eff. | Risk | **Score** | 判决 |
|-----|--------|---------|-------------|-------|--------|-------|------|------|-----------|------|
| A 发票工具 | 250 | 30 | 8 | $150 | 82 | 0.72 | 3.2 | 0.3 | **629** | SCALE |
| B 任务管理 | 180 | 12 | 3 | $120 | 65 | 0.54 | 1.5 | 0.5 | **106** | REFINE |
| C 数据可视化 | 90 | 5 | 1 | $100 | 45 | 0.43 | 0.8 | 0.6 | **26** | 观望 |
| D 日程助手 | 400 | 8 | 0 | $200 | 25 | 0.72 | 0.1 | 0.7 | **2.6** | PIVOT |
| E 加密工具 | 50 | 2 | 0 | $80 | 18 | 0.27 | 0.1 | 0.8 | **0.6** | KILL |

---

## 2. 三阶段预算模型（Phase-Gated Budget）

**核心原则**：不一次性分配全部预算。用阶段门控逐步释放，每个门控点用数据决定是否继续。

### Phase 1：最小可行信号

| 参数 | 值 |
|------|-----|
| 预算 | $50-150/MVP（按渠道调整） |
| 目标 | 30+ 着陆页访问 |
| 时间 | 3-5 天 |
| 渠道 | 单一渠道（首选 Meta，CPC 最低） |
| 度量 | CTR, 着陆页→注册转化率 |

**门控决策树**：

```
visits < 30 AND days >= 5
  → 增加预算到 $150，再跑 3 天

visits >= 30 AND signup_rate >= 3%
  → 通过！进入 Phase 2

visits >= 30 AND signup_rate 1-3%
  → 弱信号：用 /change 优化着陆页标题，重跑 Phase 1

visits >= 30 AND signup_rate < 1%
  → KILL 或彻底 PIVOT（价值主张完全不共鸣）

CTR < 0.5% after 500 impressions
  → 广告创意失败：重写标题，更换图片，重跑
```

### Phase 2：漏斗验证

| 参数 | 值 |
|------|-----|
| 预算 | $200-500/MVP |
| 目标 | 100+ 访问, 10+ 注册, 1+ 激活 |
| 时间 | 7-14 天（ads.yaml 默认 duration_days: 14） |
| 渠道 | 1-2 个渠道（加入 Google Ads 验证高意图） |
| 度量 | 完整漏斗 + Validation Scorecard + Sean Ellis 调查 |

**门控决策树**：

```
activations >= 3
  → SCALE 信号！进入 Phase 3

activations 1-2 AND signups >= 10
  → REFINE：激活摩擦是瓶颈，用 /change 简化激活流程

signups >= 10 AND activations == 0
  → 需求存在但激活破损：用 /change 重建核心动作

signups < 3 after $250 spend
  → PIVOT 或 KILL

Sean Ellis Score >= 40% (需 40+ 回复)
  → 强烈 SCALE 信号，即使激活数低也值得继续
```

### Phase 3：规模验证

| 参数 | 值 |
|------|-----|
| 预算 | $500-2,000/MVP |
| 目标 | 200+ 访问, 20+ 注册, 5+ 激活, 统计显著性 |
| 时间 | 14-21 天 |
| 渠道 | 多渠道（Google 40% + Meta 30% + Twitter/Reddit 15% + 有机 15%） |
| 度量 | CAC, LTV:CAC 比, 漏斗稳定性, 留存 |

**只有通过 Phase 2 的 MVP 才能进入 Phase 3。**

**门控决策树**：

```
CAC < 5x 行业基准 AND activations >= 5
  → 验证通过：/harden 生产化

CAC < 3x 行业基准 AND D7 retention > 20%
  → 卓越信号：全力 SCALE

CAC > 5x 行业基准 after $1000 spend
  → 渠道经济不可行：PIVOT 渠道或定价

LTV:CAC < 1:1 after optimization
  → KILL：单位经济学无法成立
```

---

## 3. 多 MVP 组合分配

### 3.1 初始分配：等额探索

```
当所有 MVP 都在 Phase 1（零数据）时：
初始预算_每个MVP = min($100, 总预算 / N)
```

**不要根据直觉做初始分配。** 零数据时所有 MVP 信息价值相等。

### 3.2 Half-Kelly 总预算计算

Kelly 准则决定你应该把多少总资金分配到 MVP 实验：

```
f* = (p × b - 1) / (b - 1)

p = P(MVP 成功) ≈ 15-25%（行业基准）
b = 成功 MVP 的回报倍数

例：p = 0.20, b = 20x
f* = (0.20 × 20 - 1) / (20 - 1) = 3/19 ≈ 15.8%

Half-Kelly（推荐）= 7.9%
→ 如果你有 $50,000 可用资金，分配 ~$4,000 到 MVP 广告实验
```

### 3.3 Thompson Sampling 动态再分配

每个测量周期（3-7 天），用贝叶斯更新重新分配预算：

```
对每个 MVP：
  α = 1 + activations（成功次数）
  β = 1 + (signups - activations)（失败次数）
  posterior = Beta(α, β)

采样：
  samples = [mvp.posterior.sample() for mvp in active_mvps]
  total = sum(samples)

分配：
  mvp.next_budget = total_budget × (sample_i / total)
```

**直觉**：赢家获得更多预算（exploitation），但随机采样保证弱 MVP 偶尔也获得预算（exploration），避免过早锁定。

### 3.4 70/20/10 工程资源分配

每两周重新评估一次（匹配 sprint 周期）：

| 表现层级 | 广告预算 | 工程资源 | 产品动作 |
|---------|---------|---------|---------|
| **冠军**（最高 Assayer Score） | 2× 预算 | 70% 团队 | `/harden` → 生产化 |
| **潜力**（中等得分） | 维持预算 | 20% 团队 | `/change` 修复瓶颈，设晋升/降级阈值 |
| **末位**（低于 kill 阈值） | 停止 | 10% 或 0% | `/retro` → `/teardown` |

### 3.5 团队规模 → 最大并行 MVP 数

| 团队规模 | 最大并行 MVP | 每个 MVP 最小投入 | 依据 |
|---------|------------|-----------------|------|
| 2-3 工程师 | 2 个 | 1 人-周/轮 | 超过 2 个协调开销 > 学习收益 |
| 4-6 工程师 | 3 个 | 2 人-周/轮 | |
| 7-10 工程师 | 4 个 | 2 人-周/轮 | |
| 10+ 工程师 | 5 个（硬上限） | 3 人-周/轮 | >5 个并行 MVP 噪声 > 信号 |

---

## 4. 渠道选择指南

### 4.1 渠道成本对比（2025 实测数据）

| 渠道 | 平均 CPC | 平均 CPM | 典型 CTR | $100 买到的点击 | 意图强度 |
|------|---------|---------|---------|--------------|---------|
| Google Search | $3.80-5.00 | — | 3-5% | 20-26 | 最高（主动搜索） |
| Google Display | $0.79-0.81 | $50.60 (B2B) | 0.3-0.5% | 123-127 | 低（被动展示） |
| Meta/Facebook | $1.06 | $8-15 | 0.8-1.5% | 94 | 中（兴趣匹配） |
| Twitter/X | $0.50-2.00 | $6-10 | 0.5-1.0% | 50-200 | 中 |
| Reddit | $0.30-1.00 | $3-8 | 0.3-0.8% | 100-333 | 中（社区信任） |
| TikTok | $0.50-1.00 | $5-15 | 0.5-1.5% | 100-200 | 低 |
| LinkedIn | $5-12 | $30-80 | 0.4-0.6% | 8-20 | 高（B2B） |

### 4.2 Phase 1 首选渠道

```
预算 < $100：Meta（CPC 最低，$1.06 平均，最快获得 30+ visits）
预算 $100-200：Meta + Google Search（验证高意图流量）
预算 > $200：Google Search 主力 + Meta 辅助
```

### 4.3 按产品类型选择

| 产品类型 | 首选渠道 | 次选渠道 | 避免 |
|---------|---------|---------|------|
| B2B SaaS | Google Search | LinkedIn | TikTok |
| Consumer App | Meta | TikTok | LinkedIn |
| Developer Tool | Reddit Organic | Twitter Organic | Meta |
| E-commerce | Meta | Google Shopping | Reddit |
| Crypto/Web3 | Twitter Ads | Reddit | Google（政策限制） |
| 内容/媒体 | Twitter Organic | Reddit Organic | Google Search |

### 4.4 多渠道预算分配（Phase 3）

**默认分配**（你的 distribute.md 中已定义）：

| 渠道 | 分配比例 | 理由 |
|------|---------|------|
| Google Ads | 40% | 最高意图（搜索行为） |
| Meta Ads | 30% | 最广触达（兴趣定向） |
| Twitter Ads | 15% | 互动导向 |
| 有机渠道 | 15% | 时间投入，非预算 |

**按品类微调**：
- Developer tool → Reddit organic +10%, Meta -10%
- B2B SaaS → Google +10%, Twitter -10%
- Consumer App → Meta +10%, Google -10%
- 迭代后 → 根据最低 cost-per-activation 渠道重新分配

### 4.5 Meta 平台学习阶段注意事项

Meta 算法需要 **每周每广告组 50 次转化事件** 才能退出学习阶段：

```
如果优化目标 = activate（CPA $50）→ 最低周预算 $2,500
如果优化目标 = signup_complete（CPA $10）→ 最低周预算 $500

建议：Phase 1-2 使用 signup_complete 作为 Meta 优化目标
     Phase 3 切换到 activate（数据量已够）
```

---

## 5. 漏斗基准数据（2025-2026）

### 5.1 冷流量付费广告漏斗

| 阶段 | Kill Zone | 一般 | 好 | 卓越 | 数据来源 |
|------|-----------|------|-----|------|---------|
| **广告 CTR** | < 0.5% | 0.5-1% | 1-3% | > 5% | Google/Meta benchmarks |
| **着陆页→注册** | < 2% | 2-5% | 5-10% | > 15% | Unbounce 41K 页面 |
| **注册→激活** | < 15% | 15-30% | 30-50% | > 65% | SaaS benchmarks |
| **免费→付费（无信用卡）** | < 4% | 4-10% | 10-15% | > 25% | SaaS trial data |
| **免费→付费（需信用卡）** | < 25% | 25-35% | 35-50% | > 60% | SaaS trial data |
| **Freemium→付费** | < 1% | 1-3% | 3-5% | > 10% | Industry data |
| **Day 1 留存** | < 10% | 10-20% | 20-35% | > 50% | App analytics |
| **Day 7 留存** | < 5% | 5-10% | 10-20% | > 30% | App analytics |
| **Day 30 留存** | < 2% | 2-7% | 7-15% | > 25% | App analytics |
| **月流失率** | > 8% | 5-8% | 3-5% | < 1% | SaaS median |
| **周环比增长** | < 1% | 1-3% | 3-7% | > 7% | YC benchmark |

### 5.2 SaaS 着陆页转化率参考

- **跨行业中位数**：6.6%（Unbounce 41,000+ 页面数据集）
- **SaaS 中位数**：3.8%（低于平均，因为产品复杂度更高）
- **Top 25%**：5%+
- **Top 10%**：11.45%+
- **B2B 平均**：13.3%（高于 B2C 的 9.9%）

### 5.3 CAC 估算公式

```
CAC_estimate = CPC / (Landing_CR × Signup_CR × Activation_CR × Payment_CR)

                                漏斗各步转化率
                        ┌─────────────────────────┐
例 1（乐观）：$1.06 / (8% × 40% × 50% × 15%) = $442
例 2（中等）：$2.00 / (5% × 30% × 50% × 10%) = $2,667
例 3（悲观）：$5.00 / (3% × 20% × 30% × 5%) = $55,556

关键洞察：漏斗任何一步提升 2x 都让 CAC 降低 50%
```

---

## 6. 判决矩阵

### 6.1 `/iterate` 判决框架

来自你的模板 `iterate.md`，核心是 **pace 值**：

```
pace = (achieved / target) / (elapsed_days / total_days)
```

| 条件 | 判决 | 含义 |
|------|------|------|
| time < 25% AND visits < 30 | **TOO EARLY** | 数据不够，继续跑 |
| pace >= 0.7 | **SCALE** | 在轨！优化最大瓶颈 |
| pace 0.4-0.7, time < 60% | **REFINE** | 落后但可追，修复瓶颈 |
| pace 0.2-0.4, time > 50% | **PIVOT** | 有信号但角度错，换定位 |
| pace < 0.2, time > 50% | **KILL** | 不太可能达标 |
| 0 activations, time > 30% | **KILL** | 零需求信号 |

### 6.2 Assayer Score → 动作映射

| Assayer Score | 判决 | 广告动作 | 工程动作 | 下一步 |
|--------------|------|---------|---------|-------|
| > 300 | SCALE | 2× 预算，多渠道扩展 | 50-70% 团队 | `/harden` → 生产化 |
| 100-300 | REFINE | 维持预算，优化创意 | 20-30% 团队 | `/change` 修复瓶颈 |
| 30-100 | 观望 | 维持最小预算 | 10% 团队（诊断） | `/iterate` 等更多数据 |
| 10-30 | PIVOT | 暂停广告 | 5% 团队（重新定位） | 改 experiment.yaml |
| < 10 | KILL | 停止广告 | 0% | `/retro` → `/teardown` |

### 6.3 广告数据→判决映射（`/iterate` Step 5）

当广告跑完 `budget.duration_days` 或预算耗尽时：

| 信号 | 解读 | 动作 |
|------|------|------|
| 3+ 付费激活 | 需求验证 ✅ | 增加预算或 `/change` 提升转化 |
| 1-2 付费激活 | 弱信号 | 延长 3 天或优化着陆页 |
| 0 激活, >10 注册 | 激活问题 | `/change` 降低激活摩擦 |
| 0 激活, >50 点击, <3 注册 | 着陆页问题 | `/change` 优化着陆页 |
| 0 激活, <50 点击, <1% CTR | 定向问题 | 修改 ads.yaml 定向，重跑 `/distribute` |
| 0 激活, <50 点击, >1% CTR | 预算/时间不足 | 延长预算或时间 |

### 6.4 Sequoia Arc 产品-市场契合原型

| 原型 | 描述 | 关键信号 | 预算策略 |
|------|------|---------|---------|
| **Hair on Fire** | 解决紧急已知问题 | 用户立即采用，产品自销 | 激进 Phase 2-3，快速扩展 |
| **Hard Fact** | 新方案解决公认问题 | 理解后转化，初始采用较慢 | 耐心 Phase 2，内容营销辅助 |
| **Future Vision** | 开创新行为 | 需要教育市场 | 保守预算，有机渠道优先 |

---

## 7. Kill 标准（硬停止信号）

**任何一条满足即应考虑停止**：

| # | 信号 | 阈值 | 数据要求 |
|---|------|------|---------|
| 1 | 着陆页→注册转化率 | < 2% | 经过 3 轮广告创意迭代后，2,000+ visitors |
| 2 | Sean Ellis PMF Score | < 15% "very disappointed" | 50+ 回复 |
| 3 | 零重复使用 | 100+ 注册后 4 周内无人回访 | 4 周数据 |
| 4 | 连续 3 周指标下降 | 周环比 metric 持续走低 | 3+ 周数据 |
| 5 | CAC > 5× 行业基准 | 经过渠道和着陆页优化后 | 200+ 点击 |
| 6 | 0 activations | 花完 50% 总预算后 | Phase 2 |
| 7 | CTR < 0.5% | 500+ 印象后 | Phase 1 |

### YC "危险中间地带"

> **最难杀死的不是完全失败的 MVP——而是有"一点点 traction"的 MVP。**

特征：2-4% 周增长、20-35% PMF score、3-5% 着陆页转化率。

**对策**：设置硬性时间窗口——如果 MVP 在 **6-8 周积极迭代后** 仍未从"interesting"跨入"strong"阈值，杀掉它。不要被沉没成本绑架。

---

## 8. 实操流程：与 mvp-template 集成

### 8.1 完整生命周期

```
Step 1: /spec 'idea' × N
        ↓
        生成 N 个 experiment.yaml

Step 2: /bootstrap × N → /deploy × N
        ↓
        N 个活跃 MVP

Step 3: /distribute × N（Phase 1: $50-150/MVP，单渠道）
        ↓
        每个 MVP 生成 ads.yaml

Step 4: 等 3-5 天
        ↓

Step 5: /iterate × N
        ↓
        每个 MVP 生成 iterate-manifest.json
        （含 verdict, bottleneck, funnel_scores）

Step 6: 计算 Assayer Score，排名所有 MVP
        ↓
        ┌─────────────────────────────────┐
        │ Score > 300 → Phase 2 预算      │
        │              + 70% 工程资源      │
        │                                  │
        │ Score 30-300 → /change 修瓶颈   │
        │               维持预算           │
        │                                  │
        │ Score < 30 → /retro → /teardown │
        │              释放预算            │
        └─────────────────────────────────┘

Step 7: 每 3-7 天重复 Step 5-6
        （Thompson Sampling 动态再分配）

Step 8: 找到 SCALE 判决的 MVP
        → /harden → 生产化
        → 其余 MVP → /retro → /teardown
```

### 8.2 iterate-manifest.json 中的关键字段

`/iterate` 自动生成 `.runs/iterate-manifest.json`：

```json
{
  "experiment_id": "quickbill",
  "round": 1,
  "verdict": "SCALE",
  "bottleneck": {
    "stage": "signup_complete → activate",
    "conversion": "22%",
    "diagnosis": "Users sign up but don't create first invoice",
    "dimension": "DEMAND",
    "ratio": 0.65,
    "recommendation": "Improve CTA clarity and onboarding flow"
  },
  "funnel_scores": {
    "reach":    { "score": 85, "confidence": "reliable", "sample_size": 250 },
    "demand":   { "score": 65, "confidence": "directional", "sample_size": 30 },
    "monetize": { "score": 40, "confidence": "insufficient", "sample_size": 8 },
    "retain":   null
  }
}
```

**用这些字段计算 Assayer Score**：
- `funnel_scores.*.score` → Signal 的四个维度
- `funnel_scores.*.confidence` → Confidence 的 sample_factor
- `verdict` → 快速判决参考

### 8.3 ads.yaml 中的关键字段

```yaml
budget:
  total_budget_cents: 10000    # $100 总预算
  duration_days: 7             # 测量窗口

thresholds:
  expected_activations: 2
  go_signal: "3+ activations from paid traffic in 7 days"
  no_go_signal: "0 activations after $50 spend"

guardrails:
  max_cpc_cents: 500           # $5 CPC 上限
```

---

## 9. 测量节奏

### 9.1 按 MVP 数量调整

| 活跃 MVP 数 | 测量周期 | 每轮预算/MVP | 总实验周期 |
|------------|---------|------------|----------|
| 2-3 个 | 每 7 天 | $100-150 | 3-4 周 |
| 4-6 个 | 每 5 天 | $75-100 | 2-3 周 |
| 7-10 个 | 每 3 天 | $50-75 | 2 周 |

### 9.2 检查点日历模板

```
| 里程碑       | 日期        | 动作                    |
|-------------|------------|------------------------|
| Phase 1 检查 | Day 5      | /iterate → Phase 1 门控 |
| 首次排名     | Day 5      | 计算 Assayer Score      |
| Phase 2 检查 | Day 12     | /iterate → Phase 2 门控 |
| 决策点       | Day 14     | REFINE/KILL 判决生效    |
| 窗口关闭     | Day 21     | /retro 回顾             |
```

### 9.3 立即触发重排（不等周期）

- 任何 MVP 的 Assayer Score 突破 300
- 任何 MVP 触发硬 Kill 标准
- 竞争对手发布类似产品
- 团队人员变动

---

## 10. 高级方法

### 10.1 贝叶斯停止规则

```
先验：Beta(5, 95)  ← 行业基准 5% 转化率

每批 50-100 访客后更新后验：

  P(CR > minimum_viable_rate) > 90%  → SCALE
  P(CR > minimum_viable_rate) < 10%  → KILL
  否则                               → 继续收集数据

最小观察期：200+ 访客
不要在 200 访客前做任何判决（假阳性风险太高）
```

### 10.2 Hill 饱和函数——渠道最优花费

```
f(x) = x^S / (K^S + x^S)

K = 半饱和点（花费 K 时获得 50% 最大效果）
最优投资区间 = 1x 到 3x K

实操：
  如果 Google Ads 在 $300 时获得 50% 最大 activations
  → 最优花费 $300-900
  → 超过 $900 边际回报急剧下降
  → 省下的钱投给其他 MVP 或渠道
```

### 10.3 Sean Ellis PMF 调查执行指南

**时机**：Phase 2 结束后（已有 40+ 注册用户）

**问题**："如果不能再使用 [产品名]，你会感到多失望？"

| 选项 | 占比 | 含义 |
|------|------|------|
| 非常失望 | **这是关键数字** | PMF 指标 |
| 有点失望 | | 产品有用但非必需 |
| 不失望 | | 没解决真问题 |
| 不适用 | 排除 | 不算入总数 |

**决策**：
- 40%+ 选"非常失望" → PMF 达成，SCALE
- 25-39% → 接近但需迭代
- < 25% → 产品没解决核心痛点

**要求**：至少 40 个回复（排除"不适用"后）

### 10.4 A/B 测试样本量参考

传统统计显著性对 MVP 几乎不可能达到：

| 基准转化率 | 检测 50% 相对提升 | 检测 25% 相对提升 |
|-----------|-----------------|-----------------|
| 3% | 每组 4,800 访客 | 每组 21,000 访客 |
| 5% | 每组 2,600 访客 | 每组 11,600 访客 |
| 10% | 每组 1,500 访客 | 每组 7,300 访客 |

**结论**：MVP 不应该追求 A/B 测试的统计显著性。用贝叶斯方法（10.1）+ 方向性信号（30+ 样本）做决策。

---

## 附录：快速参考卡

### A. 一页决策流程

```
问：该投广告吗？
  → 有 experiment.yaml + 已 deploy？是 → /distribute
  → 否 → /spec → /bootstrap → /deploy 先

问：投多少？
  → Phase 1：$50-150（单渠道，Meta 首选）
  → Phase 2：$200-500（通过 Phase 1 门控后）
  → Phase 3：$500-2000（通过 Phase 2 门控后）

问：投给哪个 MVP？
  → 零数据：等额分配
  → 有数据：按 Assayer Score 排名，Thompson Sampling 动态分配

问：什么时候停？
  → 触发任何 Kill 标准 → /retro → /teardown
  → 6-8 周未达 "strong" 阈值 → 杀掉

问：什么时候全力投入？
  → Assayer Score > 300 → /harden → 生产化
  → Sean Ellis >= 40% → 全力 SCALE
  → LTV:CAC > 3:1 → 规模化
```

### B. 预算速算表

```
总可用资金 × Half-Kelly (8%) = MVP 实验总预算
MVP 实验总预算 / MVP 数量 = 每个 MVP 初始预算
每个 MVP 初始预算 × Phase 倍数 = 该 Phase 预算

例：$50,000 可用资金，5 个 MVP
总预算 = $50,000 × 8% = $4,000
每 MVP = $4,000 / 5 = $800
Phase 1 = $100, Phase 2 = $300, Phase 3 = $400（如果到了）
```

### C. 每日检查清单

```
□ 查看广告平台 dashboard（CTR, CPC, spend）
□ 查看 PostHog 漏斗（按 utm_source 过滤）
□ 任何渠道 CTR < 0.5%？→ 暂停，重写创意
□ 任何渠道花完预算？→ 触发 /iterate
□ 到测量周期了？→ 所有 MVP 跑 /iterate → 重新排名
```
