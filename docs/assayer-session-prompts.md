# Assayer — 从零构建 Session Prompts

> 20 sessions + 5 checkpoints。每个 prompt 是一个独立的 Claude Code 指令。
> 每个 session 对应一个新的 conversation。每个 session 产出 1+ PRs。
> 开始任何 session 前，先读 `docs/assayer-product-design.md`、`docs/ux-design.md` 和 `docs/CONVENTIONS.md`。

## 设计原则

1. **依赖驱动** — session 顺序由数据依赖图决定，不存在 forward reference
2. **合约导向** — 每个 session 声明输入/输出合约（文件 + export 签名）；下一个 session 验证前序合约
3. **从零开始** — 这是全新构建（`git init`），不存在旧代码
4. **最小充分** — 只构建 `experiment.yaml` 和两个设计文档中明确定义的内容
5. **可验证** — 每个 session 以 `npm run build` 零错误结束
6. **关键路径有代码锚点** — 计费、安全、数据一致性相关的实现不依赖 AI 推导，提供确定性代码片段

## Session Preamble Template

每个 session 开始时隐式执行以下步骤（不需要在每个 prompt 中重复）：

1. 读 `docs/assayer-product-design.md` 和 `docs/ux-design.md`（整体理解）
2. 读 `docs/CONVENTIONS.md`（代码风格锚点）
3. 读 `experiment/experiment.yaml`（scope lock）
4. **合约验证** — 检查前序 session 的输出合约（不只是文件存在，验证导出签名）：
   - 读取前序 session 声明的 **输出合约** 中的每个文件
   - 验证关键 export 存在且签名匹配（如 `export function specReducer(state: SpecState, event: SpecStreamEvent): SpecState`）
   - 如果合约不满足，先修复再继续

## Output Contract Format

每个 session 的 **输出** 段现在声明两种类型：
- **文件输出**：文件路径 + 关键 export 签名
- **DB 输出**：table 名 + 关键 column

后续 session 在 preamble 中验证这些合约。这消除了 "文件存在但签名不匹配" 的累积偏移风险。

## Checkpoint Template

Checkpoints（标记为 [CP]）不是 sessions — 它们不产出 PRs。每个 checkpoint 有一个可执行 **Prompt**（和 session 一样直接贴给 Claude Code），执行以下验证：

1. `npm run build` 零错误
2. `npm test` 通过
3. 前序 sessions 的所有输出文件存在
4. 无 TypeScript 编译错误（`npx tsc --noEmit`）
5. 关键 API routes 的 curl smoke test（如适用）
6. `quality: production` — 本阶段已实现 behaviors 的 `tests` 条目均有对应 spec test assertion。缺失的覆盖必须补上。
7. 生成 checkpoint report（markdown），记录：通过/失败项、发现的问题、修复建议

Checkpoint 失败时：修复问题后重新验证，不继续下一个 phase。

## 进度追踪

| Session | Status | PR / Commit | Notes |
|---------|--------|-------------|-------|
| -1 | TODO | — | External Service Setup（人工操作，非 Session）|
| 0 | TODO | — | mvp-template 补全（在 mvp-template repo 执行）|
| 1 | TODO | — | experiment.yaml + experiment/EVENTS.yaml (manual) |
| 2 | TODO | — | /bootstrap |
| 2.5 | TODO | — | Style Contract (CONVENTIONS.md) |
| 3 | TODO | — | DB schema (19 tables) + RLS + Auth + Core CRUD + Portfolio tables |
| 4 | TODO | — | SSE Spec Stream + Anonymous Specs + Claim |
| [CP1] | TODO | — | Checkpoint: Foundation + Data Layer |
| 5 | TODO | — | Landing + Assay + Signup Gate |
| 6a | TODO | — | Build & Launch Flow |
| 6b | TODO | — | Experiment Page + Change Request + Alerts |
| [CP2] | TODO | — | Checkpoint: UI Core |
| 7 | TODO | — | Lab + Verdict + Compare + Settings + Portfolio Intelligence UI + Distribution ROI display |
| 8 | TODO | — | Billing + Operations + Portfolio plan gates |
| [CP3] | TODO | — | Checkpoint: Full UI + Billing |
| 9a | TODO | — | Skill Execution API + Realtime (Vercel) |
| 9b | TODO | — | Docker + skill-runner.js (Cloud Run) |
| 10 | TODO | — | Distribution System (6 Adapters) + Distribution Plan Generator |
| [CP4] | TODO | — | Checkpoint: Infrastructure |
| 11 | TODO | — | Metrics Cron + Alerts + Verdict Engine + Notifications (email + browser push) + Portfolio crons + Distribution ROI + Confidence Bands |
| 12a | TODO | — | CSS Tokens + 6 Mobile Components + Mobile Lab NEEDS ATTENTION |
| 12b | TODO | — | Animation Choreography + Per-Page Mobile |
| 12c | TODO | — | Visual Verification |
| [CP5] | TODO | — | Checkpoint: Complete Application |
| 13 | TODO | — | /harden + /verify |
| 14 | TODO | — | /deploy + Validation |

---

## Phase -1: External Service Setup（人工操作，非 Session）

> **在执行任何 Session 之前**，完成以下外部服务注册和配置。这些步骤不能被 Claude Code 自动化 — 需要人工在各平台的 Dashboard 中操作。Session 1 开始前，所有 ✅ 项必须完成；⏳ 项可以在对应 Session 之前完成。

### ✅ Session 1 前必须就绪

| 服务 | 操作 | 产出（填入 .env） | 验证方式 |
|------|------|-------------------|----------|
| **GitHub** | 创建 `assayer` repo（private） | repo URL | `git clone` 成功 |
| **Supabase** | 创建 project（region: 选择离目标用户最近的） | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | Supabase Dashboard → Settings → API |
| **Supabase Auth** | 启用 Email provider + 配置 Google OAuth + GitHub OAuth | Google Client ID/Secret 填入 Supabase Dashboard | Supabase Dashboard → Authentication → Providers |
| **PostHog** | 创建 project（US/EU Cloud） | `NEXT_PUBLIC_POSTHOG_KEY`, `NEXT_PUBLIC_POSTHOG_HOST` | PostHog → Project Settings |
| **Anthropic** | 获取 API key | `ANTHROPIC_API_KEY` | `curl` 测试 |
| **Vercel** | 创建 account（Pro plan $20/mo） | Vercel CLI `vercel login` 成功 | `vercel whoami` |
| **域名** | 注册 `assayer.io` + 配置 Vercel DNS | Vercel Dashboard → Domains | `dig assayer.io` |

### ⏳ Session 8 前就绪（Billing）

| 服务 | 操作 | 产出 | 验证方式 |
|------|------|------|----------|
| **Stripe** | 创建 account（test mode）+ 创建 2 个 Product/Price: Pro $99/mo recurring, Team $299/mo recurring | `STRIPE_SECRET_KEY`, `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `STRIPE_PRO_PRICE_ID`, `STRIPE_TEAM_PRICE_ID` | Stripe Dashboard → Products |
| **Stripe Webhook** | 添加 endpoint `https://assayer.io/api/webhooks/stripe`（部署前用 `stripe listen --forward-to`） | `STRIPE_WEBHOOK_SECRET` | `stripe trigger checkout.session.completed` |

### ⏳ Session 9 前就绪（Infrastructure）

| 服务 | 操作 | 产出 | 验证方式 |
|------|------|------|----------|
| **GCP** | 创建 project + 启用 Cloud Run API + Artifact Registry API | `GCP_PROJECT_ID`, `GCP_REGION` | `gcloud projects describe` |
| **GCP Service Account** | 创建 SA（roles: Cloud Run Invoker + Artifact Registry Reader）+ 下载 JSON key | `GCP_SA_KEY`（base64 编码的 JSON） | `gcloud auth activate-service-account` |
| **Docker image** | Build + push to Artifact Registry（Session 9b 构建） | `CLOUD_RUN_JOB_NAME` | `docker pull` 成功 |
| **Railway** | 创建 account + 获取 API token | `RAILWAY_TOKEN` | `railway whoami` |
| **Cloudflare**（用于 Railway experiments DNS） | 获取 API token + Zone ID for assayer.io | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID` | `curl -H "Authorization: Bearer $TOKEN" https://api.cloudflare.com/client/v4/zones` |

### ⏳ Session 10 前就绪（Distribution）

| 服务 | 操作 | 产出 | 验证方式 |
|------|------|------|----------|
| **Twitter/X** | Developer Portal → 创建 App → OAuth 2.0 PKCE | `TWITTER_CLIENT_ID`, `TWITTER_CLIENT_SECRET` | OAuth callback 测试 |
| **Reddit** | 创建 App（script type） | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | OAuth callback 测试 |
| **Resend** | 创建 account + 验证 assayer.io domain | `RESEND_API_KEY` | `curl` 发送测试邮件 |
| **Google Ads** | 创建 MCC account + Developer Token（test mode）+ OAuth app | `GOOGLE_ADS_MCC_ID`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_DEVELOPER_TOKEN` | Google Ads API 测试调用 |
| **Meta Ads** | 创建 Business Manager + Facebook Login App（`ads_management` scope）| `META_APP_ID`, `META_APP_SECRET` | Meta Graph API 测试 |
| **Twitter Ads** | Developer Portal → Ads API access | `TWITTER_ADS_CONSUMER_KEY`, `TWITTER_ADS_CONSUMER_SECRET` | Ads API 测试 |

### ⏳ Session 11 前就绪（Notifications）

| 服务 | 操作 | 产出 | 验证方式 |
|------|------|------|----------|
| **VAPID keys** | `npx web-push generate-vapid-keys` | `NEXT_PUBLIC_VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT=mailto:support@assayer.io` | 本地生成即可 |

### ⏳ Session 13 前就绪（Monitoring）

| 服务 | 操作 | 产出 | 验证方式 |
|------|------|------|----------|
| **Sentry** | 创建 Next.js project | `SENTRY_DSN`, `SENTRY_AUTH_TOKEN` | Sentry Dashboard |

### Ad Platform Production Access Timeline

> Test mode 足以完成 Session 10-14。Production access 在 /deploy 后按需申请。

| 平台 | Test Access | Production Access | 阻塞 Session？ |
|------|------------|-------------------|---------------|
| Google Ads | 立即可用（test account） | Basic access ~1 周 | 否 |
| Meta Ads | 立即可用（Sandbox） | App review ~2 周 | 否 |
| X Ads API | Developer portal 注册 | Approval ~1 周 | 否 |

---

## Phase 0: Template Prerequisites

### Session 0 — mvp-template 补全（在 mvp-template repo 执行）

**目标**：补全 mvp-template 中 Assayer 所依赖的 8 项能力：4 个 distribution stack files + 4 个 skill 增强。

**为什么这是 Session 0**：Assayer Session 10（Distribution System）会调用 `/distribute` skill，该 skill 读取 `stacks/distribution/*.md` 生成 per-channel config。如果这些 stack files 不存在，Session 10 无法工作。同理，Session 2 的 `/bootstrap` 需要 vitest co-install 逻辑（Assayer 用 `testing: playwright` + `quality: production`，需要两套 test runner 共存）。Session 9a 的 skill-runner 需要 `/iterate` 输出 iterate-manifest.json，Session 4 的 spec stream 需要 `/spec` 共享 spec-reasoning.md 规则。

**输入**：mvp-template 仓库（当前 main 分支）

**输出合约**（Assayer Session 2/9a/10 会验证这些文件存在且内容符合格式）：
```
.claude/stacks/distribution/meta-ads.md        → frontmatter 含 assumes/packages/files/env/ci_placeholders/clean 字段
.claude/stacks/distribution/twitter-organic.md  → frontmatter 全空（config-only），含 API Procedure section
.claude/stacks/distribution/reddit-organic.md   → frontmatter 全空（config-only），含 API Procedure section
.claude/stacks/distribution/email-campaign.md   → frontmatter env.server 含 RESEND_API_KEY
.claude/commands/bootstrap.md                   → 含 "Vitest co-installation" 段落（搜索此字符串验证）
.claude/commands/spec.md                        → 含 "spec-reasoning.md" 引用 + STOP points
.claude/commands/iterate.md                     → 含 "iterate-manifest.json" 输出定义 + per-hypothesis verdicts
.claude/commands/distribute.md                  → 含 6 adapters 列表 + channel selection logic
```

**注意**：此 session 在 mvp-template repo 中执行，不在 Assayer repo 中。

**Prompt**:

```
这是 mvp-template 的补全任务。Assayer（一个基于此 template 构建的产品）依赖以下 8 项尚不存在的能力。
不要修改现有功能的行为 — 只新增文件或在现有文件中追加内容。

## Phase 1: 发现 — 读取所有参考文件

先读以下文件，理解现有格式和约定（不修改）：

1. `.claude/stacks/distribution/google-ads.md` — distribution stack 的标准格式（frontmatter 结构 + section 顺序）
2. `.claude/stacks/distribution/twitter.md` — Twitter Ads stack（区分 ads vs organic）
3. `.claude/stacks/distribution/reddit.md` — Reddit Ads stack（区分 ads vs organic）
4. `.claude/stacks/email/resend.md` — email stack 格式（区分 transactional vs campaign）
5. `.claude/commands/bootstrap.md` — 当前 bootstrap 流程（找到 Phase 2 "Production quality check" 段的插入位置）
6. `.claude/commands/spec.md` — 当前 /spec skill
7. `.claude/commands/iterate.md` — 当前 /iterate skill
8. `.claude/commands/distribute.md` — 当前 /distribute skill（确认现有 adapter 数量）
9. `.claude/stacks/testing/vitest.md` — vitest stack 格式（bootstrap.md 修改需要引用）
10. `.claude/patterns/spec-reasoning.md` — spec 推理规则（spec.md 修改需要引用）

**格式规则**：从 google-ads.md 提取精确的 frontmatter schema 和 section 顺序。所有新建的 distribution stack files 必须与 google-ads.md 保持相同的 frontmatter 字段集和 section 命名模式。

## Phase 2: 实施 — 分 3 个 PR

### PR 1: 4 个 distribution stack files

branch: `feat/distribution-stacks`

#### 1a. 新建 `.claude/stacks/distribution/meta-ads.md`

Meta Marketing API v21.0。**与 google-ads.md 的关键区别**：targeting 是 interest-based（非 keyword-based），conversion tracking 走 Meta Pixel + Conversions API（非 Google Tag）。

Frontmatter（所有字段必须存在，即使为空 — distribution stacks 是 config-only）：
```yaml
assumes: []
packages:
  runtime: []
  dev: []
files: []
env:
  server: []
  client: []
ci_placeholders: {}
clean:
  files: []
  dirs: []
  gitignore: []
```

必须包含的 Sections（名称严格匹配 google-ads.md 的 section 命名模式）：
- **Ad Format Constraints**: Single image（1200×628, primary text ≤125 chars, headline ≤40 chars）, Carousel（2-10 cards）, Video（15-60s）
- **Targeting Model**: Interest-based + demographic + lookalike audiences + custom audiences (Pixel) + location/language
- **Click ID**: fbclid（自动追加）
- **Conversion Tracking**: Meta Pixel（client-side: `fbq('track','Lead')`）+ Conversions API（server-side: `POST graph.facebook.com/v21.0/{pixel_id}/events`）。建议 server-side 以应对 iOS 14.5+
- **Policy Restrictions**: 金融广告需 disclaimers，crypto 需 written permission，ad review ~24h
- **Cost Model**: CPM 或 CPC，bidding LOWEST_COST（初始）→ COST_CAP（50+ conversions 后）。MVP 建议 CPC + LOWEST_COST
- **Config Schema** (ads.yaml):
  ```yaml
  channel: meta-ads
  campaign:
    name: string
    objective: OUTCOME_TRAFFIC
    budget_cents_per_day: integer
    start_date: date
    end_date: date
  adset:
    targeting: { interests, demographics, locations, languages }
    bid_strategy: LOWEST_COST
    optimization_goal: LINK_CLICKS
  ad:
    creative: { image_url, primary_text, headline, cta: LEARN_MORE }
    tracking: { pixel_id, utm_source: facebook, utm_medium: paid_social }
  ```
- **UTM**: `utm_source=facebook`, `utm_medium=paid_social`
- **Setup Instructions**: Create Meta Business Manager → add ad account → install Meta Pixel → Create Facebook Login app → configure OAuth (`ads_management` scope) → test in Sandbox
- **API Procedure**（8 步）:
  1. Get access token via Facebook Login OAuth
  2. Get ad account ID: `GET /v21.0/me/adaccounts`
  3. Create campaign: `POST /v21.0/act_{ad_account_id}/campaigns`
  4. Create ad set: `POST /v21.0/act_{ad_account_id}/adsets`（含 targeting spec）
  5. Upload image: `POST /v21.0/act_{ad_account_id}/adimages`
  6. Create ad creative: `POST /v21.0/act_{ad_account_id}/adcreatives`
  7. Create ad: `POST /v21.0/act_{ad_account_id}/ads`（关联 creative + adset）
  8. Set campaign status ACTIVE: `POST /v21.0/{campaign_id} { status: 'ACTIVE' }`
- **Error Handling**（表格格式）:

  | Error | Action |
  |-------|--------|
  | OAuthException | refresh token |
  | #1 Unknown error | retry with backoff |
  | #17 Rate limit | exponential backoff |
  | #100 Invalid param | check targeting spec |

#### 1b. 新建 `.claude/stacks/distribution/twitter-organic.md`

Organic posting via X API v2。**不是** X Ads API — ads 在 `twitter.md` 已覆盖。此文件覆盖免费有机发布。

Frontmatter: 与 google-ads.md 完全相同结构（所有字段为空 — config-only）。

必须包含的 Sections：
- **Post Format**: Tweet thread（最多 25 tweets, 每条 ≤280 chars）, 支持 media upload（images, video）, URL 自动缩短为 t.co（消耗 23 chars）
- **Auth**: OAuth 2.0 PKCE, scopes: `tweet.write`, `tweet.read`, `users.read`。Basic tier 即可（不需要 Elevated access）
- **Rate Limits**: `POST /2/tweets` — 300/3h per app, 200/15min per user; media upload — 615/15min
- **Measurement**: X API v2 free tier 无 organic analytics API。使用 UTM params + PostHog 追踪。每条 tweet link 附加 `utm_source=twitter&utm_medium=organic`
- **Config Schema** (organic.yaml):
  ```yaml
  channel: twitter-organic
  thread:
    - { text: string, media_url?: string }
  reply_settings: "mentionedUsers"
  ```
- **Setup**: X Developer Portal → create Project + App → enable OAuth 2.0 → callback URL → generate keys
- **API Procedure**:
  1. Post first tweet: `POST /2/tweets { text: "..." }`
  2. Thread replies: `POST /2/tweets { text: "...", reply: { in_reply_to_tweet_id: prev_id } }`（循环）
  3. Media upload（if applicable）: `POST /2/media/upload`（chunked）→ get `media_id` → include in tweet payload
- **Notes**: 不要使用 automated thread bots pattern（违反 X Platform Manipulation Policy）。发布间隔建议 ≥30s 以避免质量过滤

#### 1c. 新建 `.claude/stacks/distribution/reddit-organic.md`

Organic posting via Reddit API。**不是** Reddit Ads API — ads 在 `reddit.md` 已覆盖。

Frontmatter: 全空（与 twitter-organic.md 相同结构）。

必须包含的 Sections：
- **Post Format**: Link post 或 Self post。Title ≤300 chars。Self post body 支持 Markdown
- **Subreddit Rules**: 每个 subreddit 有独立 self-promotion 限制。发布前 `GET /r/{subreddit}/about/rules` 检查。常见限制: karma 门槛, 账号年龄, 10:1 participation ratio
- **Flair**: 某些 subreddit 要求 flair。`GET /r/{subreddit}/api/link_flair` → 选择最匹配的 flair
- **Auth**: OAuth 2.0, scopes: `submit`, `read`, `flair`。User-Agent 必须包含 app name + version
- **Rate Limits**: 10 requests/min（全局），每 subreddit 发帖间隔 ≥10min
- **Measurement**: UTM params in link URL。Reddit 不提供 post analytics API
- **Config Schema** (organic.yaml):
  ```yaml
  channel: reddit-organic
  posts:
    - { subreddit: string, title: string, type: "link"|"self", url?: string, body?: string, flair_id?: string }
  ```
- **Setup**: reddit.com/prefs/apps → create app → get client_id + secret → OAuth 2.0 authorization
- **API Procedure**:
  1. Get access token: `POST /api/v1/access_token`
  2. Get subreddit rules: `GET /r/{subreddit}/about/rules`
  3. Get flairs: `GET /r/{subreddit}/api/link_flair_v2`
  4. Submit post: `POST /api/submit { sr, kind: "link"|"self", title, url|text, flair_id? }`
- **Notes**: Reddit 社区对 spam 极度敏感。organic posts 必须提供 genuine value。建议: "Show HN" 式分享 + 后续 comment 参与

#### 1d. 新建 `.claude/stacks/distribution/email-campaign.md`

Broadcast email distribution via Resend API。**与 `stacks/email/resend.md` 不同** — 那个是 transactional email（welcome, password reset），这个是 distribution campaign（launch announcements, outreach）。

Frontmatter: `env.server: [RESEND_API_KEY]`（其余全空）。

必须包含的 Sections：
- **Batch Send**: `POST /emails/batch`, max 100 recipients per call。大列表分批发送
- **Audience Management**: Resend Audiences API（`POST /audiences`, `POST /audiences/{id}/contacts`）或 BYO email list
- **Email Format**: HTML email, 必须包含: unsubscribe link（Resend 自动追加 if using Audiences）, physical address（CAN-SPAM）
- **CAN-SPAM Compliance**: physical address in footer, functional unsubscribe, no misleading headers/subjects
- **Tracking**: UTM params in all links（`utm_source=email`, `utm_medium=campaign`, `utm_campaign={slug}`）。Resend 提供 open/click tracking（webhook events: `email.opened`, `email.clicked`）
- **Config Schema** (campaign.yaml):
  ```yaml
  channel: email-campaign
  campaign:
    subject: string
    from: string
    reply_to: string
    html_template: string
    audience_id?: string
    contacts?: string[]
    utm_params: { utm_source: email, utm_medium: campaign, utm_campaign: string }
  ```
- **Setup**: Resend account → verify sending domain（DNS records）→ create API key → create Audience
- **API Procedure**:
  1. Create/get audience: `POST /audiences` or `GET /audiences`
  2. Add contacts: `POST /audiences/{id}/contacts { email, first_name?, last_name? }`
  3. Batch send: `POST /emails/batch [{ from, to, subject, html, headers: { "X-Entity-Ref-ID": unique_id } }]`
  4. Track delivery: Resend webhook → `email.delivered` / `email.bounced` / `email.complained`
- **Notes**: 不是 newsletter 平台。用于实验 launch announcement / distribution reach。每个 experiment 最多 2-3 batch emails

**PR 1 验证**：
1. 4 个新文件都存在于 `.claude/stacks/distribution/`
2. 每个文件的 frontmatter 字段集与 `google-ads.md` 完全一致（字段名 + 嵌套结构）
3. 每个文件都有 Config Schema section + API Procedure section
4. `email-campaign.md` 的 `env.server` 包含 `RESEND_API_KEY`；其他 3 个 `env` 全空

### PR 2: bootstrap.md + spec.md 修改

branch: `feat/bootstrap-spec-enhancements`

#### 2a. 修改 `.claude/commands/bootstrap.md` — vitest co-install

**插入位置**：找到字符串 `"scaffold-wire: run test discovery checkpoint"`，在其所在段落之后插入新段落。如果找不到该字符串，找到 Phase 2 中包含 "Production quality check" 或 "quality: production" 的位置，在相关检查列表中追加。

**插入内容**（原文，不改动措辞）：

```markdown
**Vitest co-installation**: When `quality: production` is set AND `stack.testing` is NOT `vitest` (e.g., `testing: playwright`):
- Also install `vitest` and `@vitest/coverage-v8` as dev dependencies
- Create `vitest.config.ts` using the template from `.claude/stacks/testing/vitest.md`
- This ensures specification tests (TDD per `patterns/tdd.md`) can run alongside E2E tests
- scaffold-setup handles this: check if vitest.config.ts exists before creating
- Two test runners coexist: `npx playwright test` for E2E, `npx vitest run` for spec tests
```

**为什么**：Assayer 使用 `testing: playwright`（E2E）+ `quality: production`（需要 vitest 做 spec tests）。没有这段逻辑，bootstrap 不会安装 vitest，Session 3 的 unit tests 无法运行。

#### 2b. 修改 `.claude/commands/spec.md` — 导入 spec-reasoning.md

读取 `.claude/patterns/spec-reasoning.md`，理解其 6 个 reasoning section 的结构。

修改 spec.md，使 /spec skill：
- 在执行推理时 import `.claude/patterns/spec-reasoning.md` 作为 shared reasoning rules（在文件中添加读取指令）
- 包装为带 3 个 STOP points 的交互式流程：
  1. Pre-flight Reasoning → **STOP**（等待用户确认方向）
  2. Hypothesis Quality Review → **STOP**（等待用户审核假设）
  3. Variant Distinctiveness Review → **STOP**（等待用户选择变体策略）
- Output format: `experiment.yaml`（CLI 不使用 `>>>EVENT:` — 那是 SSE streaming 专用格式）
- Reuse spec-reasoning.md 的 6 个 reasoning sections，不重复定义

**PR 2 验证**：
1. `bootstrap.md` 中搜索 `"Vitest co-installation"` 能找到完整段落
2. `spec.md` 中搜索 `"spec-reasoning.md"` 能找到引用
3. `spec.md` 中搜索 `"STOP"` 能找到 3 个 stop points

### PR 3: iterate.md + distribute.md 修改

branch: `feat/iterate-distribute-enhancements`

#### 3a. 修改 `.claude/commands/iterate.md` — per-hypothesis verdicts + manifest

增强 /iterate skill，添加以下能力：

**Per-hypothesis verdicts**：每个 hypothesis 独立判定，不仅仅是 experiment-level verdict。
- 判定值：`CONFIRMED` / `REJECTED` / `INCONCLUSIVE`
- 每个 hypothesis 独立评估，基于其关联的 metrics

**Archetype-specific funnel mapping**（当前 iterate 只处理 web-app funnel，增加 service 和 cli）：
- service: REACH = API adoption rate, DEMAND = integration requests, ACTIVATE = first successful API call, MONETIZE = API key upgrades, RETAIN = monthly active integrations
- cli: REACH = install rate, DEMAND = daily active usage, ACTIVATE = first successful command, MONETIZE = pro feature adoption, RETAIN = update rate

**Output 定义** — iterate-manifest.json:
```json
{
  "experiment_id": "<experiment.yaml name>",
  "round": 1,
  "verdict": "<SCALE|KILL|PIVOT|REFINE|TOO_EARLY>",
  "bottleneck": {
    "stage": "<funnel stage name>",
    "conversion": "<percentage>",
    "diagnosis": "<one-line diagnosis>",
    "dimension": "<REACH|DEMAND|ACTIVATE|MONETIZE|RETAIN>",
    "ratio": 0.65,
    "recommendation": "<dimension-specific recommendation>"
  },
  "recommendations": [
    {
      "action": "<what to do>",
      "skill": "</change ...>",
      "expected_impact": "<which metric improves>"
    }
  ],
  "variant_winner": "<slug or null>",
  "analyzed_at": "<ISO 8601>",
  "hypothesis_verdicts": [
    {
      "hypothesis_id": "<id from spec-manifest>",
      "metric_formula": "<metric.formula from hypothesis>",
      "metric_operator": "<metric.operator from hypothesis>",
      "computed_value": "<result of evaluating formula against event counts>",
      "threshold": "<metric.threshold from hypothesis>",
      "verdict": "<CONFIRMED|REJECTED|INCONCLUSIVE|BLOCKED>",
      "blocked_by": "<parent hypothesis id or null>",
      "sample_size": 0,
      "confidence_level": "<insufficient data|directional signal|reliable|high confidence>"
    }
  ],
  "funnel_scores": {
    "reach": { "score": 0, "confidence": "<tag>", "sample_size": 0, "threshold_source": "<hypothesis|events-yaml>" },
    "demand": { "score": 0, "confidence": "<tag>", "sample_size": 0, "threshold_source": "<hypothesis|events-yaml>" },
    "activate": { "score": 0, "confidence": "<tag>", "sample_size": 0, "threshold_source": "<hypothesis|events-yaml>" },
    "monetize": { "score": 0, "confidence": "<tag>", "sample_size": 0, "threshold_source": "<hypothesis|events-yaml>" },
    "retain": null
  }
}
```

**Input**：读取 `spec-manifest.json`（由 skill-runner.js 从 Supabase 数据生成）

#### 3b. 修改 `.claude/commands/distribute.md` — 6-adapter architecture

更新为 6-adapter architecture（确认现有 adapter 数量后追加缺失的 adapters）：

**6 adapters 完整列表**：
1. `twitter-organic` → 读取 `stacks/distribution/twitter-organic.md`
2. `reddit-organic` → 读取 `stacks/distribution/reddit-organic.md`
3. `email-resend` → 读取 `stacks/distribution/email-campaign.md`
4. `google-ads` → 读取 `stacks/distribution/google-ads.md`（已存在）
5. `meta-ads` → 读取 `stacks/distribution/meta-ads.md`
6. `twitter-ads` → 读取 `stacks/distribution/twitter.md`（已存在）

**Channel selection logic**：
- Free/PAYG plans → organic only（twitter-organic, reddit-organic, email-resend）
- Pro/Team plans → all 6 channels
- 叠加 experiment type + budget 约束

**Budget allocation**（AI-suggested split based on experiment type + target audience）：
- Default split（no history）: 40% Google Ads, 30% Meta Ads, 15% Twitter Ads, 15% organic
- Organic-only split: 40% Twitter, 35% Reddit, 25% Email

**Config generation**: 每个 adapter 生成对应的 `ads.yaml` / `organic.yaml` / `campaign.yaml`，从 experiment data 中填充字段。

**PR 3 验证**：
1. `iterate.md` 中搜索 `"iterate-manifest.json"` 能找到 output 定义
2. `iterate.md` 中搜索 `"hypothesis_verdicts"` 或 `"CONFIRMED"` 能找到 verdict 逻辑
3. `iterate.md` 中搜索 `"service:"` 和 `"cli:"` 能找到 archetype-specific funnel mapping
4. `distribute.md` 中搜索 `"meta-ads"` 和 `"twitter-organic"` 能找到 6 adapters
5. `distribute.md` 中搜索 `"Free/PAYG"` 或 `"organic only"` 能找到 channel selection logic

## Phase 3: 最终验证

所有 3 个 PR merge 后，运行以下验证：

1. 文件计数: `ls .claude/stacks/distribution/` 应包含 meta-ads.md, twitter-organic.md, reddit-organic.md, email-campaign.md（4 个新文件 + 已有文件）
2. Frontmatter 一致性: 每个新 distribution stack file 的 frontmatter 字段集与 google-ads.md 完全一致
3. 字符串搜索验证（验证修改是否到位）:
   - `grep -l "Vitest co-installation" .claude/commands/bootstrap.md` → 命中
   - `grep -l "spec-reasoning.md" .claude/commands/spec.md` → 命中
   - `grep -l "iterate-manifest.json" .claude/commands/iterate.md` → 命中
   - `grep -l "meta-ads" .claude/commands/distribute.md` → 命中
4. 无 build 验证（这些都是 .md 文件，无 npm run build）
```

---

## Phase 1: Foundation

### Session 1 — Repo + experiment.yaml + experiment/EVENTS.yaml (manual)

**目标**：创建仓库，手动编写 experiment.yaml 和 experiment/EVENTS.yaml。

**输入**：无（从零开始）

**输出**：
- `experiment/experiment.yaml` — 完整的 Assayer 平台 spec
- `experiment/EVENTS.yaml` — analytics 事件定义
- Git repo initialized

**输出合约**（Session 2 验证）：
```
experiment/experiment.yaml  → name: assayer, type: web-app, level: 3, quality: production, stack.database: supabase
experiment/EVENTS.yaml      → 含 events (flat map with funnel_stage), global_properties sections
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/assayer-product-design.md 和 docs/ux-design.md。

这是 Assayer 平台本身（不是用户的实验）的 experiment.yaml。根据两个设计文档，手动编写 experiment.yaml，覆盖全部 7 个 sections（Identity, Intent, Behaviors, Journey, Variants, Funnel, Stack）：

1. Identity:
   - name: assayer
   - type: web-app
   - level: 3（Product — 需要 auth + payments）
   - quality: production

2. Stack:
   services:
     - name: app
       runtime: nextjs
       hosting: vercel
       ui: shadcn
       testing: playwright
   database: supabase
   auth: supabase
   auth_providers: [google, github]
   analytics: posthog
   payment: stripe
   ai: anthropic

3. Intent:
   description: |
     Founders waste months building products nobody wants because they lack a fast,
     structured way to validate ideas before committing. Assayer is a verdict machine:
     paste an idea, watch AI generate a testable spec, deploy a live experiment with
     one click, and receive a data-backed SCALE/REFINE/PIVOT/KILL verdict in days.
   thesis: "If indie hackers can go from idea to live experiment verdict in under 30 minutes, then >5% of landing visitors will sign up and >40% of signups will generate a spec, as measured by signup and spec completion rates"
   target_user: Indie hackers and solo founders validating startup ideas
   distribution: Reddit (r/startups, r/SideProject, r/indiehackers), Indie Hackers, Twitter/X #buildinpublic, Google Ads, Meta Ads
   hypotheses（5 条，依赖链 h-01→h-02→h-03→h-04→h-05）:
     - id: h-01, category: reach
       statement: "Ad click-through rate exceeds 2% across paid channels"
       metric: { formula: "visit_landing / ad_impressions", threshold: 0.02, operator: gte }
       priority_score: 95, experiment_level: 1, depends_on: []
     - id: h-02, category: demand
       statement: ">5% of landing page visitors sign up for an account"
       metric: { formula: "signup_complete / visit_landing", threshold: 0.05, operator: gte }
       priority_score: 90, experiment_level: 1, depends_on: [h-01]
     - id: h-03, category: activate
       statement: ">40% of signed-up users generate at least one spec"
       metric: { formula: "spec_generated / signup_complete", threshold: 0.40, operator: gte }
       priority_score: 80, experiment_level: 2, depends_on: [h-02]
     - id: h-04, category: monetize
       statement: ">3% of signed-up users convert to Pro plan"
       metric: { formula: "pay_success / signup_complete", threshold: 0.03, operator: gte }
       priority_score: 70, experiment_level: 3, depends_on: [h-03]
     - id: h-05, category: retain
       statement: ">30% of signed-up users return within 30 days"
       metric: { formula: "retain_return / signup_complete", threshold: 0.30, operator: gte }
       priority_score: 60, experiment_level: 3, depends_on: [h-04]

4. Behaviors — 必须精确 29 条（b-01~b-29），ID 和分组如下。Checkpoints 验证规则：CP1 验证已实现的 b-16~b-29，CP2 验证 b-01~b-15，CP3 验证 b-01~b-18 + b-22~b-25（跳过 b-19~b-21 system behaviors），CP4 验证 b-01~b-18 + b-22~b-29（同样跳过 b-19~b-21），CP5 验证全部 b-01~b-29（100%）。Payment deep tests: b-22/b-23/b-25。不要重新编号或合并/拆分。

   **b-01~b-15: UI behaviors（Sessions 5-6b 实现，CP2 验证）**
   - b-01: Landing — hero 渲染，"Test it" CTA 导航到 /assay?idea=...
   - b-02: Landing — stats 查询（"X ideas tested"），pricing section，variant messaging
   - b-03: Assay creation mode — SSE streaming，spec progressive rendering（skeleton → cards）
   - b-04: Assay edit mode — 加载已有实验，Round N indicator，bottleneck highlighted
   - b-05: Signup gate — OAuth + email/password，session_token claim，free tier quota check
   - b-06: Launch Phase A-B — build + deploy progress，quality gate（L2/L3），auto-fix loop UI
   - b-07: Launch Phase C-G — content check，walkthrough，distribution approval，live confirmation
   - b-08: Experiment scorecard — 5 dimensions（REACH/DEMAND/ACTIVATE/MONETIZE/RETAIN），confidence bands
   - b-09: Experiment alerts + traffic — 7 alert types，per-channel breakdown，change request modal
   - b-10: Verdict — 4 verdict types（SCALE/KILL/REFINE/PIVOT），return flows（REFINE→edit, PIVOT→new, UPGRADE→L+1）
   - b-11: Lab — portfolio grouping（RUNNING/VERDICT READY/COMPLETED），Assayer Score ★，lineage
   - b-12: Lab advanced — AI Insight card（Pro+），Budget tab（Team），empty state
   - b-13: Compare — side-by-side 2+ experiments，Pro/Team gate，[Export CSV]
   - b-14: Settings — account，OAuth channels（login vs distribution），billing，plan comparison table
   - b-15: Mobile + Content Check — tab bar，responsive layout，inline [e] editing，swipe-to-archive

   **b-16~b-18: Core API behaviors（Sessions 3-4 实现，CP1 开始验证）**
   - b-16: Spec generation — POST /api/spec/stream（SSE，anonymous，rate limit 3/24h）+ POST /api/spec/claim（auth，quota，upgrade_from）
   - b-17: Experiments CRUD — GET/POST/PATCH/DELETE + RLS isolation + sub-resources（hypotheses, variants, rounds, metrics, alerts）+ compare + CSV export
   - b-18: Portfolio Intelligence API — GET /api/portfolio/insight，POST .../apply，POST .../dismiss，GET /api/portfolio/budget，POST .../allocate

   **b-19~b-21: System behaviors（Session 11 实现，CP5 验证。actor: system）**
   - b-19: Metrics pipeline — actor: system, trigger: vercel cron 15min。Sync PostHog events + ad platform APIs → compute 5 scorecard dimension ratios + confidence bands → compute Assayer Score (formula from product-design.md) → detect 7 alert conditions (budget_exhausted, dimension_dropping, metrics_stale, ad_account_suspended, post_removed, runtime_bug, bug_auto_fixed) → create experiment_alerts rows。tests: "cron route responds 200 with CRON_SECRET", "experiment_metric_snapshots row created", "alert created when spend > 90% budget"
   - b-20: Verdict engine + notifications — actor: system, trigger: metrics sync + force_verdict。Guard clause (clicks < 100 OR duration < 50%) → per-hypothesis verdicts (CONFIRMED/REJECTED/INCONCLUSIVE/BLOCKED) → experiment-level verdict (SCALE/KILL/REFINE/PIVOT) → distribution ROI computation → write experiment_decisions → status → verdict_ready。Notification dispatch: 7 triggers (experiment_live, first_traffic, mid_experiment, verdict_ready, budget_alert, dimension_dropping, bug_auto_fixed), email via Resend + browser push via Web Push API, notification CRUD API (GET list, PATCH read, POST mark-all-read, POST push-subscribe)。tests: "verdict computed correctly for SCALE scenario", "notification created on verdict_ready", "guard clause returns null when insufficient data"
   - b-21: Auto-fix + portfolio crons — actor: system, trigger: various crons。Runtime auto-fix: 0.0x ratio + sufficient traffic → triggerCloudRunJob(verify) → /change → redeploy → bug_auto_fixed alert (max 3 retries per dimension per 7 days)。Portfolio: AI insight generation (daily, Sonnet, 2+ running experiments) → portfolio_insights table。Auto-rebalance (daily, Team only, Thompson Sampling) → budget_allocations。Cost monitor (weekly) → margin + Cloud Run budget check ($50 alert, $100 hard limit)。Cleanup (hourly) → DELETE expired anonymous_specs + rate_limit_entries + stripe_webhook_events。Hosting billing (monthly) → $5/mo overage charge + free tier 30-day auto-pause。tests: "auto-fix creates bug_auto_fixed alert", "portfolio insight generated for user with 2+ experiments", "expired anonymous_specs deleted"

   **b-22~b-25: Payment behaviors（Session 8 实现，CP3 深度验证）**
   - b-22: Stripe webhooks — 5 event types，signature verification，idempotency（stripe_webhook_events dedup）
   - b-23: Billing gate — POST /api/operations/authorize（pool + PAYG + free + past_due check），POST .../complete，POST .../extend
   - b-24: Stripe subscription — subscribe/topup/portal routes，checkout session creation
   - b-25: Billing UX integration — pool usage display，PAYG→Pro conversion，operation classifier（Haiku），token budget enforcement（80% warning, 100% hard stop + "Continue for $X?" gate）

   **b-26~b-29: Infrastructure behaviors（Sessions 9-10 实现，CP4 验证）**
   - b-26: Skill execution — POST /api/skills/execute，triggerCloudRunJob()（共享函数 src/lib/cloud-run.ts），realtime progress（Supabase Broadcast exec:{id}），approval gate pattern（poll/resume/timeout）
   - b-27: Skill runner — Docker image，8-step workspace lifecycle，draft→active status transition，experiment_live notification（immediate），per-experiment hosting（Vercel/Railway）
   - b-28: Distribution — 6 adapters（twitter-organic, reddit-organic, email-resend, google-ads, meta-ads, twitter-ads），OAuth callbacks，getValidToken() token refresh，plan-gated channels，distribution plan generator
   - b-29: Cron + notification infrastructure — vercel.json 8 cron routes with CRON_SECRET verification，Resend email integration，Web Push API + service worker（public/sw.js），push subscription management

   **Session 11 实现 b-19~b-21 的完整逻辑** — 不是 "wiring"，是独立的系统 behaviors：
   - b-19 metrics pipeline 实现真实的 PostHog + ad platform sync（替换 seed data）
   - b-20 verdict engine 实现 per-hypothesis verdict + decision framework（之前只有 UI 展示 mock 数据）
   - b-21 auto-fix + portfolio crons 实现所有 8 个 cron route 的业务逻辑
   - CP4 验证时 b-19~b-21 尚未实现（Session 11 在 CP4 之后），CP5 要求 100% 覆盖

   每个 behavior 使用 given/when/then 格式 + tests[] 数组。
   actor: system 用于 cron jobs、webhooks、Cloud Run Jobs。
   tests[] 条目对应 quality: production 要求的 spec test assertions。

   示例格式（三种类型）：

   UI behavior:
   - id: b-01
     hypothesis_id: h-02
     given: "A visitor arrives at the Assayer landing page"
     when: "They read the value proposition and variant messaging"
     then: "The page renders with headline, subheadline, CTA, and social proof"
     tests:
       - "Landing page renders without errors"
       - "Variant-specific content displays correctly"
     level: 1

   System behavior:
   - id: b-19
     actor: system
     trigger: "vercel cron 15min"
     hypothesis_id: h-05
     given: "Running experiments exist with active distribution"
     when: "The 15-minute cron fires"
     then: "Metrics are synced from PostHog and ad platforms into experiment scorecard"
     tests:
       - "cron route responds 200 with CRON_SECRET"
       - "experiment_metric_snapshots row created"
       - "alert created when spend > 90% budget"
     level: 3

   Payment behavior:
   - id: b-23
     hypothesis_id: h-04
     given: "A user initiates subscription, top-up, or billing management"
     when: "They call /api/billing/subscribe, /api/billing/topup, or /api/billing/portal"
     then: "Stripe checkout session or billing portal URL is returned"
     tests:
       - "Subscribe creates a valid Stripe subscription checkout"
       - "Topup creates a valid PAYG top-up checkout ($10-$500)"
       - "Portal redirects to Stripe billing management"
     level: 3

5. Golden path — 从 ux-design.md Information Architecture 推导（核心路径 8 步）：
   - step: "Visit landing page", event: visit_landing, page: landing
   - step: "Enter idea, click 'Test it'", event: cta_click, page: landing
   - step: "Watch AI spec materialize", event: spec_generated, page: assay
   - step: "Sign up to save", event: signup_complete, page: assay
   - step: "Review build, approve launch", event: experiment_created, page: launch
   - step: "Monitor live experiment", event: experiment_viewed, page: experiment
   - step: "Receive verdict", event: verdict_delivered, page: verdict
   - step: "View all experiments", event: lab_viewed, page: lab
   target_clicks: 5
   注意：signup 不是独立页面，是 Assay 页面上的 modal overlay（ux-design.md Screen 3）。
   compare 和 settings 不在 golden_path 中（它们是补充页面），但包含在 Pages 列表中。
   Event names 必须与 experiment/EVENTS.yaml 中定义的 event 名称一致。

6. Variants — Assayer 自身的 A/B messaging（4 个 variant，每对 headline 词汇差异 >30%）：
   - slug: verdict-machine
     headline: "Know if it's gold before you dig."
     subheadline: "Paste your idea. Get a live experiment and a data-backed verdict in days."
     cta: "Test My Idea"
     pain_points:
       - "You spent months building something nobody wanted"
       - "Surveys and interviews give you opinions, not data"
       - "Setting up analytics, ads, and landing pages takes weeks"
     promise: "A clear SCALE/REFINE/PIVOT/KILL verdict backed by real user data"
     proof: "Built on the same validation framework used by Y Combinator founders"
     urgency: "Every week without validation is a week building the wrong thing"
   - slug: time-saver
     headline: "Stop building the wrong thing."
     subheadline: "From idea to validated experiment in 30 minutes. No code, no guesswork."
     cta: "Validate in 30 Minutes"
     pain_points:
       - "Building an MVP takes weeks even with no-code tools"
       - "You don't know if low traction means bad idea or bad execution"
       - "Pivoting after launch wastes months of effort"
     promise: "Skip months of building to find out if your idea has legs"
     proof: "Founders validated 500+ ideas in beta — average time to verdict: 5 days"
     urgency: "Your runway is burning. Get answers before you run out"
   - slug: data-driven
     headline: "Data-backed verdicts in days, not months."
     subheadline: "AI generates your experiment. Real users deliver the verdict."
     cta: "Get My Verdict"
     pain_points:
       - "You're making bet-the-company decisions on gut feeling"
       - "A/B testing requires traffic you don't have yet"
       - "Analytics tools show you what happened, not what to do"
     promise: "Replace gut feelings with funnel data and statistical confidence"
     proof: "93% of ideas that scored KILL would have failed within 6 months"
     urgency: "The market won't wait — validate now or watch someone else win"
   - slug: budget-friendly
     headline: "Validate ideas for less than a landing page costs."
     subheadline: "One click. Real traffic. A verdict you can trust — starting at $0."
     cta: "Start Free"
     pain_points:
       - "Hiring a designer for a landing page costs more than your validation budget"
       - "Ad platforms have minimum spends that eat into your runway"
       - "Most validation tools charge monthly before you know if they work"
     promise: "Get your first verdict with zero upfront cost"
     proof: "Free tier includes 3 experiments — enough to validate your top ideas"
     urgency: "Your best idea costs nothing to test. Your worst idea costs everything to build"

7. Funnel — Assayer 平台自身的验证框架：
   available_from:
     reach: L1
     demand: L1
     activate: L2
     monetize: L3
     retain: L3
   decision_framework:
     scale: "All tested dimensions >= 1.0"
     kill: "Any top-funnel (REACH or DEMAND) < 0.5"
     pivot: "2+ dimensions < 0.8"
     refine: "1+ dimensions < 1.0 but fewer than 2 below 0.8"
   （具体阈值已在 Section 3 hypotheses 中定义，funnel 只需 available_from + decision_framework。）

8. 同时编写 experiment/EVENTS.yaml，按页面分组定义所有 analytics events（~50 events）：
   global_properties: { experiment_name: "assayer", experiment_id: "platform" }

   Landing（4 events）:
     - visit_landing (reach) — user loads landing page（properties: variant, referrer, utm_source/medium/campaign/content, gclid, click_id）
     - cta_click (demand) — user clicks primary CTA（properties: variant, cta_text）
     - variant_displayed (reach) — variant messaging rendered（properties: variant, page）
     - pricing_viewed (demand) — user scrolls to pricing section（properties: variant）

   Assay（6 events）:
     - idea_submitted (activate) — user submits idea text（properties: idea_length, anonymous）
     - spec_generated (activate) — AI spec generation completes（properties: anonymous, idea_length, generation_time_ms）
     - spec_saved (activate) — user saves generated spec（properties: experiment_id）
     - spec_edited (activate) — user edits spec fields（properties: experiment_id, field）
     - spec_claimed (activate) — anonymous spec claimed after signup（properties: experiment_id）
     - round_started (activate) — user starts new experiment round（properties: experiment_id, round_number）

   Auth（3 events）:
     - signup_start (demand) — user opens signup modal（properties: method）
     - signup_complete (demand) — user successfully creates account（properties: method）
     - login_complete (retain) — existing user logs in（properties: method）

   Launch（8 events）:
     - experiment_created (activate) — user creates experiment from spec（properties: experiment_id, level）
     - build_started (activate) — build process initiated（properties: experiment_id）
     - build_completed (activate) — build finishes successfully（properties: experiment_id, duration_ms）
     - deploy_started (activate) — deploy initiated（properties: experiment_id）
     - deploy_completed (activate) — deploy finishes（properties: experiment_id, duration_ms）
     - quality_gate_passed (activate) — L2/L3 quality gate passed（properties: experiment_id, level）
     - content_check_completed (activate) — content review completed（properties: experiment_id）
     - distribution_approved (activate) — user approves distribution plan（properties: experiment_id, channels）

   Experiment（7 events）:
     - experiment_viewed (activate) — user views experiment scorecard（properties: experiment_id）
     - scorecard_dimension_clicked (activate) — user expands scorecard dimension（properties: experiment_id, dimension）
     - alert_viewed (activate) — user views alert detail（properties: experiment_id, alert_type）
     - alert_dismissed (activate) — user dismisses alert（properties: experiment_id, alert_type）
     - change_request_submitted (activate) — user submits change request（properties: experiment_id, change_type）
     - traffic_breakdown_viewed (activate) — user views per-channel traffic（properties: experiment_id）
     - distribution_launched (activate) — distribution goes live（properties: experiment_id, channels）

   Verdict（4 events）:
     - verdict_delivered (activate) — system delivers verdict（properties: experiment_id, verdict, confidence）
     - verdict_viewed (activate) — user views verdict page（properties: experiment_id, verdict）
     - return_flow_started (activate) — user starts REFINE→edit / PIVOT→new / UPGRADE→L+1（properties: experiment_id, flow_type）
     - distribution_roi_viewed (activate) — user views channel ROI breakdown（properties: experiment_id）

   Lab（6 events）:
     - lab_viewed (activate) — user views lab portfolio page（properties: experiment_count）
     - experiment_card_clicked (activate) — user clicks experiment card（properties: experiment_id）
     - lab_filtered (activate) — user filters/sorts experiment list（properties: filter_type）
     - insight_viewed (activate) — user views AI Insight card（properties: insight_id）
     - insight_applied (activate) — user applies AI recommendation（properties: insight_id, experiment_id）
     - budget_allocated (activate) — user allocates budget（properties: experiment_id, amount_cents）

   Settings（5 events）:
     - settings_viewed (retain) — user views settings page（properties: tab）
     - channel_connected (activate) — user connects OAuth distribution channel（properties: channel）
     - channel_disconnected (activate) — user disconnects a channel（properties: channel）
     - plan_comparison_viewed (monetize) — user views plan comparison table
     - billing_portal_opened (monetize) — user opens Stripe billing portal

   Server-side（7 events — trackServerEvent, not typed wrappers）:
     - pay_start (monetize, requires: [payment]) — user enters checkout flow（properties: plan, amount_cents）
     - pay_success (monetize, requires: [payment]) — payment confirmed via webhook（properties: plan, amount_cents, provider）
     - checkout_started (monetize, requires: [payment]) — Stripe checkout session created（properties: plan, amount_cents）
     - payment_complete (monetize, requires: [payment]) — checkout.session.completed webhook（properties: plan, amount_cents, provider）
     - subscription_changed (monetize, requires: [payment]) — subscription created/updated/deleted（properties: plan, status）
     - retain_return (retain) — user returns after 24+ hours（properties: days_since_last）
     - activate (activate) — core activation action completed（properties: action, fake_door）

   每个 event 需要完整的 properties 定义（type + required + description）。
   Payment events 必须有 requires: [payment]。

9. Pages 列表（来自 product-design.md Section 6 Pages）：
   landing, assay, launch, experiment, verdict, lab, compare, settings
   （共 8 个 page.tsx。signup 是 modal overlay on /assay，不是独立页面）

验证：experiment.yaml 格式正确，包含全部 7 个 sections（Identity, Intent, Behaviors, Journey, Variants, Funnel, Stack），behaviors 覆盖所有 pages 和 API route groups，golden_path events 与 experiment/EVENTS.yaml 中的 event 名称一致，hypotheses formulas 引用 experiment/EVENTS.yaml 中定义的 events。
```

---

### Session 2 — /bootstrap

**目标**：用 /bootstrap 生成完整脚手架。

**输入**：Session 1 的 `experiment/experiment.yaml` + `experiment/EVENTS.yaml`

**输出**：
- 完整的 Next.js 项目结构
- 所有 pages 的 stub（含 dynamic route segments: launch/[id], experiment/[id], verdict/[id]）
- shadcn/ui 组件安装
- PostHog analytics 集成
- Playwright + Vitest 双 test runner（quality: production 要求 vitest co-install）
- Supabase 初始配置
- `.env.example` 包含所有环境变量

**输出合约**（Session 2.5 验证）：
```
experiment/experiment.yaml             → contains `owner:` field (non-empty)
src/app/page.tsx                       → exists (Landing page stub)
src/app/assay/page.tsx                 → exists (Assay page stub)
src/app/launch/[id]/page.tsx           → exists (Launch page stub, dynamic route)
src/app/experiment/[id]/page.tsx       → exists (Experiment page stub, dynamic route)
src/app/verdict/[id]/page.tsx          → exists (Verdict page stub, dynamic route)
src/app/lab/page.tsx                   → exists (Lab page stub)
src/app/compare/page.tsx               → exists (Compare page stub)
src/app/settings/page.tsx              → exists (Settings page stub)
src/lib/analytics.ts                   → exists, PROJECT_NAME = "assayer", PROJECT_OWNER ≠ "TODO"
.env.example                           → exists with NEXT_PUBLIC_SUPABASE_URL, ANTHROPIC_API_KEY
package.json                           → contains "next", "react" in dependencies
playwright.config.ts                   → exists
vitest.config.ts                       → exists (quality: production co-install)
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中 Session 2 和 Session 1 的「输出合约」section（不要读整个文件），
执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

## Phase 0: 前置检查

1. 读 experiment/experiment.yaml。

2. 检查 `owner` 字段：
   BG1 Validation Gate 要求 `owner` 字段存在且非空。Session 1 的 prompt 未包含此字段。
   - 如果 `owner` 字段缺失或为空，在 Identity section（`name:` 下方）添加：
     ```yaml
     owner: <GitHub org 或用户名>
     ```
     通过 `gh repo view --json owner --jq '.owner.login'` 获取值。
     如果 `gh` 不可用，直接问用户要 GitHub owner。
   - 这是 analytics PROJECT_OWNER 的来源，必须在 /bootstrap 之前就位。

3. 读 experiment/EVENTS.yaml。

## Phase 1: 运行 /bootstrap

运行 /bootstrap。

### 交互点指引

/bootstrap 不是 one-shot —— 它有多个 STOP 点需要用户响应。按以下预设处理：

**STOP 1 — Phase 1 Step 6 Plan Approval**
/bootstrap 完成 Phase 1 后会展示完整 plan 并 STOP 等待审批。
Assayer 配置大（29 behaviors + 4 variants + 50 events），上下文可能接近限制。
→ **选择 option 2 "approve and clear"**。这会保存 plan 到 `.claude/current-plan.md`，
  然后你需要 /clear 并重新运行 /bootstrap，它会从 checkpoint 恢复。

**STOP 2 — Preamble: TSP-LSP check**
/bootstrap 检测 `typescript-language-server` 是否已全局安装。
→ 如果未安装，**安装它**（`npm install -g typescript-language-server typescript`）。
  它给 subagents 提供 real-time type checking，对生成正确类型代码至关重要。

**STOP 3 — Externals: Dependency Classification**
scaffold-externals subagent 会列出需要外部 credentials 的 services：
- Anthropic API — **core**（选 Provide now 或 Provision at deploy）
- Google Ads API, Meta Ads API, Twitter Ads API, Reddit API — **全部 Skip**
  （Session 10 Distribution System 负责完整构建，此时构建只会产生未使用代码）
- Stripe — 已由 `stack.payment: stripe` 覆盖，不会出现在 externals
- Resend — 如在 stack 中声明则已覆盖，否则 Skip（Session 11 处理 email）

如果有上述之外的 dependency 被检出，评估是否属于 Session 10+ 范围后决定。

## Phase 2: 验证

Bootstrap 完成后执行以下检查。每项包含 ON FAIL 操作。

1. **npm run build 零错误**
   ON FAIL: 读 build error log，修复后重新 build（max 3 attempts，参考 .claude/patterns/verify.md）

2. **8 个 pages 路径正确**（含 dynamic segments）
   ```
   src/app/page.tsx                    # landing
   src/app/assay/page.tsx              # assay
   src/app/launch/[id]/page.tsx        # launch（需要 [id]）
   src/app/experiment/[id]/page.tsx    # experiment（需要 [id]）
   src/app/verdict/[id]/page.tsx       # verdict（需要 [id]）
   src/app/lab/page.tsx                # lab
   src/app/compare/page.tsx            # compare
   src/app/settings/page.tsx           # settings
   ```
   ON FAIL: 创建缺失的 page stub（参考其他 page 格式），或修正路径（确保 launch/experiment/verdict 有 [id] segment）。

3. **analytics 库正确配置**
   检查 `src/lib/analytics.ts`（或 analytics.tsx）：
   - `PROJECT_NAME` === "assayer"
   - `PROJECT_OWNER` === experiment.yaml 中的 `owner` 值
   - PostHog provider setup 正确
   ON FAIL: 修复 constants 值。

4. **.env.example 完整**
   必须包含：NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY,
   NEXT_PUBLIC_POSTHOG_KEY, NEXT_PUBLIC_POSTHOG_HOST, ANTHROPIC_API_KEY
   ON FAIL: 追加缺失的变量。

5. **双 test runner 就绪**
   - `playwright.config.ts` 存在
   - `vitest.config.ts` 存在（quality: production + testing: playwright → vitest co-install）
   - `npx vitest run --passWithNoTests` 不报错
   ON FAIL: 如果 vitest.config.ts 缺失，参考 `.claude/stacks/testing/vitest.md` 模板创建。
   如果 vitest 未安装：`npm install -D vitest @vitest/coverage-v8`。

6. **Supabase 初始 migration 存在**
   `supabase/migrations/` 下至少 1 个 .sql 文件。
   这是 bootstrap 自动创建的初始 schema — **不要在此 session 手动添加 application tables**。
   Session 3 负责完整的 19-table schema。

## 错误恢复

如果 /bootstrap 在任何阶段崩溃或被中断：
- /bootstrap 是 idempotent — 在同一 branch 上重新运行即可
- `.claude/current-plan.md` 的 frontmatter `checkpoint` 字段记录了最新完成阶段
- 重新运行 /bootstrap 时，它读取 checkpoint 并从断点恢复
- 如果需要完全重来：`git checkout main && make clean`

Gate-keeper BLOCK 恢复：
- **BG1 BLOCK**（validation）：缺失字段 — 检查 gate-keeper 输出的 Observed 列，补充后重新运行
- **BG2 BLOCK**（orchestration）：scaffold 输出不完整 — 检查具体缺失文件，手动创建或重新运行对应 phase
- **BG3 BLOCK**（verification）：verify.md 未完成 — 告诉 Claude "complete the verification phase"
- **BG4 BLOCK**（PR）：通常是 uncommitted changes 或在 main 分支 — 检查 git status

## npm 兼容性提示

shadcn/ui + Next.js 15 + React 19 可能产生 peer dependency 冲突。
如果 `npm install` 报 ERESOLVE 错误，使用 `npm install --legacy-peer-deps`。
```

---

### Session 2.5 — Style Contract (CONVENTIONS.md)

**目标**：建立代码风格锚点，确保 14 个后续 session 的实现一致性。

**输入**：Session 2 的 bootstrap scaffold

**输出**：
- `docs/CONVENTIONS.md` — 12 sections 的代码约定文档

**输出合约**（Session 3 验证）：
```
docs/CONVENTIONS.md → exists with 12 sections (API Route Pattern through Migration Convention)
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读当前项目中已有的代码模式（如果 bootstrap 已生成 src/lib/ 下的文件）。

创建 docs/CONVENTIONS.md，包含 12 个 section，codify 以下 Assayer-specific patterns：

1. API Route Pattern — withErrorHandler(withAuth(...)) 组合，await context.params
2. Supabase Query Safety — 显式列列表，ownership checks
3. Zod Schema Conventions — .max() on strings，命名规范，export types
4. Error Response Shape — canonical { error: { code, message, details } }
5. TypeScript Type Locations — types.ts vs *-schemas.ts
6. Status Transitions — VALID_STATUS_TRANSITIONS map，validate before update
7. Test Conventions — colocated files，describe/it/expect，@/ alias
8. Import Alias — always @/，never ../../
9. Soft Delete Pattern — archived_at timestamp，never hard-delete user rows
10. Analytics Events — typed wrappers，never call PostHog directly
11. Naming — files kebab-case, components PascalCase, DB snake_case, schemas camelCase+Schema
12. Migration Convention — one per PR，DROP+ADD for CHECK constraints

这些约定补充 CLAUDE.md 的 template-level 规则 — CLAUDE.md 覆盖通用模板规则，
CONVENTIONS.md 覆盖 Assayer-specific 实现 patterns。

每个 section 包含：规则描述 + 代码示例 + 反面示例（如适用）。

npm run build 零错误（无代码修改，仅文档）。
```

---

## Phase 2: Data Layer

### Session 3 — 完整 DB Schema + RLS + Auth Middleware + Core CRUD APIs

**目标**：建立完整的数据层 — 19 张表（17 core + 2 Portfolio Intelligence）、RLS policies、auth middleware、核心 CRUD API routes。

**输入**：Session 2 的 bootstrap scaffold

**输出**：
- 19 张表的 Supabase migration（product-design.md Section 6 + Portfolio Intelligence 完整）
- 所有表的 RLS policies
- `withAuth` middleware（验证 Supabase JWT，返回 user）
- `withErrorHandler` wrapper（统一 error schema）
- Rate limiting utility
- Core CRUD API routes（experiments, hypotheses, variants, rounds）
- Supabase RPC function `decrement_payg_balance`（原子递减 PAYG 余额）
- Supabase trigger function `create_user_billing_on_signup`（新用户自动创建 billing 行）

**输出合约**（后续 session 验证）：
```
src/lib/api-error.ts        → export function withErrorHandler(handler): NextResponse
src/lib/api-auth.ts          → export function withAuth(handler): (request, context) => Promise<NextResponse>
src/lib/rate-limit.ts        → export function rateLimit(key, limit, windowMs): Promise<{success, remaining}>
src/lib/supabase-server.ts   → export function createServerClient(): SupabaseClient
vitest.config.ts             → exists
supabase/migrations/         → ≥1 .sql file with 19 CREATE TABLE statements
DB output:
  - portfolio_insights table (columns: id, user_id, insight_json, portfolio_health, top_experiment_id, created_at, dismissed_at, applied_at)
  - budget_allocations table (columns: id, user_id, allocation_json, source, applied_at)
  - experiments.assayer_score column (integer, 0-100, nullable)
  - experiments.score_updated_at column (timestamptz, nullable)
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/assayer-product-design.md Section 5（API Routes）和 Section 6（Data Model）。

用 /change 实现完整数据层。这是一个大的 change，分几个 PR：

## PR 1: Error Schema + Auth Middleware + Rate Limiting

1. 创建 `src/lib/api-error.ts`：
   - ErrorResponse type: { error: { code, message, details } }
   - codes: validation_error, not_found, unauthorized, rate_limited, ai_error, internal_error
   - withErrorHandler HOF wrapping route handlers

2. 创建 `src/lib/api-auth.ts`：
   - withAuth(handler) — 从 request headers 提取 Supabase JWT，验证，返回 user
   - withAuth wraps handler signature: (request, context, user)
   - context.params 是 Promise<Record<string, string>>

3. 创建 `src/lib/rate-limit.ts`：
   - 双层 rate limiting（Vercel serverless 无跨实例共享内存）：
     - **Critical routes（auth, billing, spec/stream）**: Supabase-backed — INSERT into `rate_limit_entries` table（columns: key, window_start, count, expires_at），用 upsert + count 查询。Supabase 自带连接池，延迟 ~5ms，可接受。
     - **General API routes**: In-memory Map + 60s cleanup interval（per-instance，defense-in-depth，冷启动重置可接受）
   - `rate_limit_entries` 表加入 Session 3 PR2 migration（不计入 19 张 core tables，纯 infra 表）：
     ```sql
     CREATE TABLE rate_limit_entries (
       key text NOT NULL,
       window_start timestamptz NOT NULL DEFAULT now(),
       count integer NOT NULL DEFAULT 1,
       expires_at timestamptz NOT NULL,
       PRIMARY KEY (key, window_start)
     );
     CREATE INDEX idx_rate_limit_expires ON rate_limit_entries (expires_at);
     -- Cleanup: cron/cleanup route 同时清理 expired rate_limit_entries
     ```
   - 配置：auth routes 5/min, spec/stream 3/24h per session_token（但 spec/stream 的 rate limit 直接查 anonymous_specs 表 count，不经过 rate-limit.ts）, billing routes 10/min, general 30/min
   - Export: `rateLimit(key: string, limit: number, windowMs: number, backend?: 'supabase' | 'memory'): Promise<{ success: boolean, remaining: number }>`

4. 创建 vitest 配置（quality: production 要求 specification tests，Playwright stack 不创建 vitest.config.ts）：
   - npm install -D vitest @vitest/coverage-v8
   - 创建 vitest.config.ts（添加 @ → src/ alias）
   - 为 api-error.ts, api-auth.ts, rate-limit.ts 编写 unit tests

## PR 2: 完整 DB Schema（19 tables）

创建 Supabase migration，包含 product-design.md Section 6 的所有 19 张表（17 core + 2 Portfolio Intelligence）：

1. anonymous_specs — 匿名 spec 暂存（24h TTL）
2. experiments — 实验主表
3. experiment_rounds — 多轮 REFINE 支持
4. hypotheses — 假设
5. hypothesis_dependencies — 假设依赖关系
6. research_results — 研究结果
7. variants — A/B 变体
8. experiment_metric_snapshots — 时序指标快照
9. experiment_decisions — verdict 历史
10. experiment_alerts — 告警（7 种 alert_type，包括 bug_auto_fixed）
11. notifications — 通知（7 种 trigger_type，包括 bug_auto_fixed）
12. ai_usage — AI 使用追踪
13. user_billing — 用户计费（plan, PAYG balance, pool counters）
14. operation_ledger — 操作账本
15. skill_executions — Cloud Run Jobs 追踪
16. oauth_tokens — 分发渠道 OAuth tokens
17. distribution_campaigns — 分发 campaigns

注意：所有表启用 RLS。Policy 模式：
- 直属 user_id 的表: auth.uid() = user_id
- 通过 experiment_id 关联的表: experiment_id IN (SELECT id FROM experiments WHERE user_id = auth.uid())
- anonymous_specs: 无 RLS（匿名访问）

包含所有 indexes、CHECK constraints、updated_at triggers，完全匹配 product-design.md Section 6 的 SQL。

## PR 2b: Supabase RPC + Triggers（关键代码锚点）

**这些是计费正确性的基础，必须作为 migration 的一部分创建。**

### 1. 新用户自动创建 user_billing 行

```sql
-- Auto-create user_billing row when a new user signs up via Supabase Auth
CREATE OR REPLACE FUNCTION public.create_user_billing_on_signup()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.user_billing (user_id, plan, payg_balance_cents)
  VALUES (NEW.id, 'payg', 0)
  ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.create_user_billing_on_signup();
```

**为什么不在 app logic 中创建**：如果 claim API 或任何其他路径在 user_billing 行存在之前被调用，会产生 FK violation 或 null reference。Trigger 保证原子性。

### 2. PAYG 余额原子递减 RPC

```sql
-- Atomic PAYG balance decrement (prevents race conditions)
CREATE OR REPLACE FUNCTION public.decrement_payg_balance(
  p_user_id uuid,
  p_amount_cents integer
)
RETURNS integer AS $$
DECLARE
  new_balance integer;
BEGIN
  UPDATE public.user_billing
  SET payg_balance_cents = payg_balance_cents - p_amount_cents,
      updated_at = now()
  WHERE user_id = p_user_id
    AND payg_balance_cents >= p_amount_cents
  RETURNING payg_balance_cents INTO new_balance;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Insufficient PAYG balance'
      USING ERRCODE = 'P0001';
  END IF;

  RETURN new_balance;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

**调用方式**（Session 8 completion handler 使用）：
```typescript
const { data, error } = await supabase.rpc('decrement_payg_balance', {
  p_user_id: user.id,
  p_amount_cents: priceCents,
});
```

### 3. Free Tier 实验数量检查 RPC

```sql
-- Check if user can create a new experiment (Free tier = 1 lifetime limit)
CREATE OR REPLACE FUNCTION public.check_experiment_quota(p_user_id uuid)
RETURNS jsonb AS $$
DECLARE
  user_plan text;
  experiment_count integer;
  payg_balance integer;
BEGIN
  SELECT plan, payg_balance_cents INTO user_plan, payg_balance
  FROM public.user_billing WHERE user_id = p_user_id;

  SELECT COUNT(*) INTO experiment_count
  FROM public.experiments
  WHERE user_id = p_user_id AND archived_at IS NULL;

  -- Free tier: plan = 'payg' AND payg_balance = 0 AND no subscription
  -- Free tier gets 1 lifetime experiment
  IF user_plan = 'payg' AND payg_balance = 0 AND experiment_count >= 1 THEN
    RETURN jsonb_build_object(
      'allowed', false,
      'reason', 'free_tier_limit',
      'experiment_count', experiment_count,
      'message', 'Free accounts include 1 experiment. Top up your PAYG balance or upgrade to Pro.'
    );
  END IF;

  RETURN jsonb_build_object('allowed', true, 'experiment_count', experiment_count);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

**Free tier 定义**（product-design.md）：`plan = 'payg'` + `payg_balance_cents = 0` + 无 stripe_subscription_id。这不是一个独立的 plan 值 — 它是 PAYG 的零余额状态。Session 8 的 billing gate 在 authorize 时调用此 RPC。

Status transitions（作为 CHECK constraints）：
- experiments.status: draft, active, paused, verdict_ready, completed, archived
- skill_executions.status: pending, running, paused, completed, failed, timed_out
  （注：budget exceeded 不是独立 status — 使用 `paused` + `gate_type = 'budget_exceeded'`，与 approval gate pattern 一致）
- distribution_campaigns.status: draft, paused, active, completed, failed
- hypotheses.status: pending, testing, passed, failed, skipped, blocked
- experiment_alerts.alert_type 包含 bug_auto_fixed

## PR 3: Core CRUD API Routes

实现以下 routes（全部需要 auth，使用 withAuth + withErrorHandler）：

Experiments:
- GET    /api/experiments — list（paginated, grouped by status）
- GET    /api/experiments/:id — get single（含 latest round data）
- POST   /api/experiments — create（from claimed spec data）
- PATCH  /api/experiments/:id — update status/url/decision
- DELETE /api/experiments/:id — soft delete（设置 archived_at）

Sub-resources:
- POST/GET /api/experiments/:id/hypotheses — mode: append|replace
- POST/GET /api/experiments/:id/variants — variants CRUD
- POST/GET /api/experiments/:id/insights — scorecard + decision history
- POST/GET /api/experiments/:id/research — research results
- GET/POST /api/experiments/:id/rounds — rounds 管理

注意事项：
- 所有 GET 使用显式列列表（不用 SELECT *），防止信息泄露
- 所有 POST body 使用 zod 验证，string 字段加 .max() 约束
- Pagination: ?page=1&limit=20（max 100）
- Sub-resource POST 支持 mode=append（默认）和 mode=replace

## Portfolio Intelligence Tables

Add these to the same migration file:

1. Add columns to `experiments` table:
   - `assayer_score integer CHECK (assayer_score BETWEEN 0 AND 100)` — computed score for portfolio ranking
   - `score_updated_at timestamptz` — last score computation timestamp

2. Create `portfolio_insights` table:
   - `id uuid PRIMARY KEY`
   - `user_id uuid REFERENCES auth.users(id)`
   - `insight_json jsonb NOT NULL` — AI-generated recommendations (see product-design.md for schema)
   - `portfolio_health integer NOT NULL CHECK (portfolio_health BETWEEN 0 AND 100)`
   - `top_experiment_id uuid REFERENCES experiments(id)`
   - `created_at`, `dismissed_at`, `applied_at` timestamps
   - RLS policy: user_isolation (same pattern as experiments)
   - Index on user_id + active insights (WHERE dismissed_at IS NULL AND applied_at IS NULL)

3. Create `budget_allocations` table:
   - `id uuid PRIMARY KEY`
   - `user_id uuid REFERENCES auth.users(id)`
   - `allocation_json jsonb NOT NULL` — allocation per experiment (see product-design.md for schema)
   - `source text NOT NULL CHECK (source IN ('ai_recommended', 'user_custom', 'auto_rebalance'))`
   - `applied_at timestamptz`
   - RLS policy: user_isolation

每个 PR 完成后 npm run build 零错误。
```

---

### Session 4 — SSE Spec Streaming + Anonymous Specs + Claim Flow

**目标**：实现核心的 spec 生成流程 — AI 流式生成 spec、匿名暂存、登录后认领。

**输入**：Session 3 的数据层

**输出**：
- `POST /api/spec/stream` — SSE 流式 spec 生成
- `POST /api/spec/claim` — 认领匿名 spec（含 check_experiment_quota 调用）
- `src/lib/spec-stream-parser.ts` — `>>>EVENT:` 解析器
- 前端 `specReducer` — 累积 SSE events 为 UI state

**输出合约**（Session 5 验证）：
```
src/lib/spec-stream-parser.ts → export function parseSpecStreamLine(line: string): SpecStreamEvent | null
src/lib/spec-reducer.ts       → export function specReducer(state: SpecState, event: SpecStreamEvent): SpecState
                               → export type SpecState = { meta, cost, preflight[], hypotheses[], variants[], funnel[], status, ... }
                               → export type SpecStreamEvent = (union of 10 event types)
                               → export const initialSpecState: SpecState
src/app/api/spec/stream/route.ts → POST handler returning SSE Response
src/app/api/spec/claim/route.ts  → POST handler returning { experiment_id: string }
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/assayer-product-design.md Section 3（Flow 1: Idea → Spec）和 Section 5（>>>EVENT: Streaming Protocol）。
读 docs/ux-design.md Screen 2（The Assay）。

用 /change 实现 SSE spec streaming：

## 1. POST /api/spec/stream（无需 auth）

这是 Assayer 最核心的 endpoint — 匿名用户输入 idea，AI 实时流式生成完整 spec。
System prompt 的 AI reasoning rules 来自 `.claude/patterns/spec-reasoning.md`（shared with CLI /spec skill），外加 `>>>EVENT:` JSON output format 指令。

Request body:
```typescript
{
  idea: string,         // >= 20 chars
  level?: 1 | 2 | 3,   // default 1
  session_token: string, // browser-generated UUID
  regenerate_token?: string  // id of previous anonymous_spec to replace (skip rate limit)
}
```

实现：
a. Zod 验证 input（idea >= 20 chars, .max(10000)）
b. Rate limit: anonymous 3 per session_token per 24h（查 anonymous_specs 表 count）; authenticated free accounts 5 per user_id per 24h（查 anonymous_specs + experiments 表 count）
b2. Regenerate handling: 当 regenerate_token 存在时：
    - 验证该 anonymous_spec row 属于当前 session_token
    - 跳过 rate limit 检查
    - 删除旧的 anonymous_spec row
    - 后续步骤正常创建新 row（net effect: row 被替换，count 不增加）
c. 调用 Anthropic API（Opus 4.6），system prompt 指示输出 >>>EVENT: JSON markers
d. 流式解析 Claude 文本输出，提取 >>>EVENT: 行，解析 JSON
e. 转发为 SSE events（data: {json}\n\n）
f. 流结束后，将完整 spec 存入 anonymous_specs 表（session_token, spec_data, preflight_results, idea_text）
g. 24h TTL（expires_at = now + 24h）

SSE Event Types（来自 product-design.md）：
```typescript
type SpecStreamEvent =
  | { type: 'meta'; name: string; level: number; experiment_type: string }
  | { type: 'cost'; build_cost: number; ad_budget: number; estimated_days: number }
  | { type: 'preflight'; dimension: 'market' | 'problem' | 'competition' | 'icp';
      status: 'pass' | 'caution' | 'fail'; summary: string; confidence: string }
  | { type: 'preflight_opinion'; text: string }
  | { type: 'hypothesis'; id: string; category: string; statement: string;
      metric: { formula: string; threshold: number; operator: 'gt'|'gte'|'lt'|'lte' };
      priority_score: number; experiment_level: number; depends_on: string[] }
  | { type: 'variant'; slug: string; headline: string; subheadline: string;
      cta: string; pain_points: string[]; promise: string; proof: string;
      urgency: string | null }
  | { type: 'funnel'; available_from: Record<string, string> }
  | { type: 'complete'; spec: FullSpecData; anonymous_spec_id: string }
  | { type: 'input_too_vague' }
  | { type: 'error'; message: string };
```

System prompt 要求 Claude 以 inference mode 运行 — 绝不问 follow-up questions，aggressive inference，标记 [inferred] 值。

## 2. >>>EVENT: 解析器

创建 `src/lib/spec-stream-parser.ts`：
- 逐行扫描 Claude 的文本输出
- 匹配 `>>>EVENT:` 前缀
- JSON.parse 提取结构化事件
- Skip 解析失败的行（continue）
- 将 complete event 的 spec 暂存

## 3. 前端 specReducer

创建 `src/lib/spec-reducer.ts`：
```typescript
export function specReducer(state: SpecState, event: SpecStreamEvent): SpecState {
  switch (event.type) {
    case 'meta':              return { ...state, meta: event };
    case 'cost':              return { ...state, cost: event };
    case 'preflight':         return { ...state, preflight: [...state.preflight, event] };
    case 'preflight_opinion': return { ...state, preflightOpinion: event.text };
    case 'hypothesis':        return { ...state, hypotheses: [...state.hypotheses, event] };
    case 'variant':           return { ...state, variants: [...state.variants, event] };
    case 'funnel':            return { ...state, funnel: [...state.funnel, event] };
    case 'complete':          return { ...state, status: 'complete', fullSpec: event.spec, anonymousSpecId: event.anonymous_spec_id };
    case 'input_too_vague':   return { ...state, status: 'too_vague' };
    case 'error':             return { ...state, status: 'error', error: event.message };
    default:                  return state;
  }
}
```

## 4. POST /api/spec/claim（需要 auth）

登录后认领匿名 spec：
a. 接收 { session_token, upgrade_from?: string }
b. 查 anonymous_specs by session_token
c. 从 spec_data 创建 experiment + hypotheses + variants
   - 当 upgrade_from 存在时：设置新 experiment 的 parent_experiment_id = upgrade_from，将原 experiment status → 'completed'（graduated）
d. 删除 anonymous_specs row
e. 返回 { experiment_id }

## 5. Error Handling

参照 product-design.md Spec Stream Error Handling：
- Claude API timeout → SSE error event
- 格式错误 → skip，继续处理
- Rate limit → 429 response
- Network disconnect → 支持重试（same session_token 不消耗 quota）
- Supabase write failure → 降级处理，spec 保留在 frontend memory

每个文件 npm run build 零错误。
```

---

### [CP1] Checkpoint: Foundation + Data Layer

**验证范围**：Sessions 1-4 的所有输出。

**检查项**：
1. `npm run build` 零错误
2. `npx tsc --noEmit` 零错误
3. `npm test` 通过
4. 19 张表（17 core + 2 Portfolio Intelligence: portfolio_insights, budget_allocations）+ 2 infra tables（rate_limit_entries, stripe_webhook_events）的 migration 存在且语法正确
5. RLS policies 覆盖所有表
6. Core CRUD routes 可 curl 测试（需 Supabase local dev running）：
   - `POST /api/spec/stream` 返回 SSE events
   - `GET /api/experiments` 返回 200（with auth header）
   - `POST /api/spec/claim` 返回 experiment_id（with auth + session_token）
7. `docs/CONVENTIONS.md` 存在且包含 12 sections
8. `experiment/experiment.yaml` 和 `experiment/EVENTS.yaml` 格式正确
9. `quality: production` — 已实现 behaviors (b-16~b-29) 的 `tests` 条目均有对应 spec test assertion（参照 patterns/tdd.md § Specification Tests）。缺失的覆盖必须补上。

**输出**：CP1 verification report（markdown）。失败项必须修复后才能进入 Phase 3。

**CP1 通过后，立即执行 Seed Data 步骤**（不需要单独 PR，在 CP1 修复 PR 中一起完成）：

创建 `supabase/seed.sql`，包含开发环境所需的最小 seed 数据：

```sql
-- Seed data for local development (supabase db reset will run this)
-- Creates a test user with experiments in various states for UI development

-- Test user (email: test@assayer.io, created via Supabase Auth in local dev)
-- Run `supabase auth create-user --email test@assayer.io --password test1234` first

-- After user exists, insert billing row + sample experiments:
-- 1 RUNNING experiment (with metric_snapshots for scorecard rendering)
-- 1 VERDICT_READY experiment (with experiment_decisions row for verdict page)
-- 1 COMPLETED experiment (with KILL verdict for post-mortem)
-- 1 DRAFT experiment (for assay edit mode)
-- Sample hypotheses, variants, alerts, notifications for each
-- Sample distribution_campaigns for traffic section
-- Sample portfolio_insight for AI Insight card testing
```

**为什么**：Sessions 5-7 构建 UI 页面，需要真实数据才能验证 scorecard、verdict、lab cards、alerts 等组件的渲染。没有 seed data，开发者只能看到空状态或 loading skeleton。

同时在 `package.json` 中添加 script: `"db:seed": "supabase db reset"`（重置 + seed 一步完成）。

**Prompt**:

```
执行 [CP1] Checkpoint: Foundation + Data Layer。

验证范围：Sessions 1-4 的所有输出。

步骤：

1. 运行自动化检查：
   - `npm run build`（零错误）
   - `npx tsc --noEmit`（零错误）
   - `npm test`（全部通过）
   如有失败，修复后重新运行，最多 3 次。

2. 验证数据层：
   - 确认 19 张表（17 core + portfolio_insights + budget_allocations）+ 2 infra tables（rate_limit_entries, stripe_webhook_events）的 migration 存在于 supabase/migrations/ 且语法正确
   - 确认所有表启用 RLS 且有对应 policies
   - 确认 docs/CONVENTIONS.md 存在且包含 12 sections
   - 确认 experiment/experiment.yaml 和 experiment/EVENTS.yaml 格式正确（YAML 可解析）

3. behavior.tests 覆盖验证（quality: production）：
   读 experiment/experiment.yaml 中 behaviors b-16 到 b-29（API + system/cron behaviors）。
   对每个 behavior 的 tests 条目，在对应的 *.test.ts 文件中 grep 确认有 it()/test() assertion。
   缺失的覆盖：按 patterns/tdd.md § Specification Tests 补上 spec test。
   补完后重新运行 npm test 确认通过。

4. 生成 checkpoint report 写入 docs/cp1-report.md：
   - 检查项逐条通过/失败
   - behavior.tests 覆盖率（N/M 条目有 assertion）
   - 发现的问题和修复记录

所有检查项通过后，报告结果。失败项必须修复后才能进入 Phase 3。
```

---

## Phase 3: UI Core

### Session 5 — Landing Page + Assay Page + Signup Gate

**目标**：实现前三个核心页面 — 用户从输入 idea 到看到完整 spec 到注册。

**输入**：Session 4 的 SSE streaming + specReducer + claim flow

**输出**：
- Landing page（Screen 1: one input field）
- Assay page（Screen 2: spec materializing in final form）
- Signup Gate（Screen 3: save your experiment）
- Pre-flight caution UI

**输入合约验证**（Session 开始时执行）：
```bash
# 验证 Session 4 输出合约
grep -q "export function specReducer" src/lib/spec-reducer.ts || echo "FAIL: specReducer missing"
grep -q "export type SpecState" src/lib/spec-reducer.ts || echo "FAIL: SpecState type missing"
grep -q "export type SpecStreamEvent" src/lib/spec-reducer.ts || echo "FAIL: SpecStreamEvent type missing"
grep -q "export const initialSpecState" src/lib/spec-reducer.ts || echo "FAIL: initialSpecState missing"
test -f src/app/api/spec/stream/route.ts || echo "FAIL: spec stream route missing"
test -f src/app/api/spec/claim/route.ts || echo "FAIL: spec claim route missing"
```

**输出合约**（Session 6a 验证）：
```
src/app/page.tsx                      → Landing page with idea input + "Test it" CTA
src/app/assay/page.tsx                → Assay page with SSE streaming + specReducer + edit mode
src/components/signup-gate.tsx        → Modal overlay component with Google/GitHub/email auth
src/components/preflight-caution.tsx  → Pre-flight warning with [Proceed anyway] + [Adjust idea]
```

**Prompt 1 of 3 — Landing Page**（新对话）:

```
读 docs/assayer-session-prompts.md Session 5 的「输入合约验证」段落，执行验证：
- grep -q "export function specReducer" src/lib/spec-reducer.ts
- grep -q "export type SpecState" src/lib/spec-reducer.ts
- grep -q "export type SpecStreamEvent" src/lib/spec-reducer.ts
- grep -q "export const initialSpecState" src/lib/spec-reducer.ts
- test -f src/app/api/spec/stream/route.ts
- test -f src/app/api/spec/claim/route.ts
如果任何验证失败，先修复再继续。

读 docs/ux-design.md Screen 1（Landing）。
读 docs/CONVENTIONS.md。

这是 Session 5 /change 1 of 3。用 /change 实现 Landing Page 重构：

### 现状（bootstrap 产物，需重构）

`src/app/page.tsx` 是 `"use client"` 组件，导入 `src/components/landing-content.tsx`（~840 行）。
当前 hero：headline + CTA link（直接跳转 /assay，无输入框）+ 右侧 verdict demo card。
Below-fold：pain points（3 列 grid）+ how it works（4 步 alternating layout）+ social proof animated counters + trust signals + verdict showcase + final CTA。
没有输入框、没有 DB-backed stats、没有 pricing section、没有 URL param 传递。
Variant 页面 `/v/[slug]` 也使用 `landing-content.tsx` — 不要影响 variant 页面。

### 改动要点

1. `page.tsx` → server component：移除 `"use client"`，server-side 查询 DB stats（revalidate: 3600），渲染 landing shell
2. Hero 重构为 input-first：移除 verdict demo card + CTA link，替换为大输入框 + "Test it →"。输入部分提取为新的 client component（如 `src/components/landing-hero-input.tsx`）
3. Below-fold 复用 + 调整：从 `landing-content.tsx` 提取/改造可复用 sections。How it works 改为 3 步。移除 verdict showcase。新增 pricing section + stats grid
4. `landing-content.tsx` 保留给 `/v/[slug]`，不删除（variant 页面继续使用它）

### 目标结构

"One sentence for one answer" — 整个 above-the-fold 只有一个输入框。

- 标题: "Know if it's gold before you dig."
- 副标题: Describe your idea → AI designs the experiment → code deploys → traffic flows from 6 channels → you get a verdict in days, not months.
- 大输入框: "Describe your business idea..."（textarea）
- CTA: "Test it →"
- 示例: [AI resume builder] [Meal prep planner]
- 底部: "312 ideas tested . 67 confirmed worth building"
  Data source: Landing page server component queries `SELECT count(*) FROM experiments WHERE status IN ('active','completed','verdict_ready')` for "ideas tested" 和 `SELECT count(*) FROM experiment_decisions WHERE decision = 'scale'` for "confirmed worth building"。Cache 1 hour（Next.js `revalidate: 3600`）。初始启动时 hardcode `312` / `67` 直到真实数据超过 50 行。使用 Supabase service role key（server component，不暴露给 client）。
- Advanced options 折叠: type selector (web-app/service/cli) + level selector (L1/L2/L3)，默认 web-app + L1
- 不显示定价 above the fold（ux-design.md 明确要求：landing page sells the experience, not the plan）

Below-the-fold sections（滚动可见）：
- Pain Points section: 3 条用户痛点引用（vertical stack），例如 "I spent 6 months building something nobody wanted"
- How It Works section: 3-step vertical timeline: Describe your idea → AI designs the experiment → Get a verdict in days
- Stats grid（2×2）: Ideas tested / Money saved / Avg time to verdict / Accuracy — 数据来源同 hero 底部统计（server component query, revalidate: 3600）
- Pricing section: Plan cards（Free / PAYG / Pro / Team），滚动到底部可见但不在 above-the-fold 推广
  Plan comparison table 必须包含 ux-design.md 的完整行：Spec generation, Create experiments, Modifications, Content edits, Auto-fix, Hosting, Paid distribution, Portfolio Intelligence, **Team seats**（1/1/1/5）, **Priority build**（--/--/--/Yes）, Overage。
  Team seats 和 Priority build 是 pricing display 行项 — MVP 不实现 multi-user 或 priority queue 功能，仅在 plan comparison 中显示为 Team differentiator。

点击 "Test it" → 导航到 /assay，传递 idea text。
传递机制: URL search params `?idea=encodeURIComponent(text)&type=web-app&level=1`。
不要使用 sessionStorage 或 React state — URL params 保证刷新后不丢失、支持分享链接。

npm run build 零错误。
```

**Prompt 2 of 3 — Assay Page**（新对话）:

```
读 docs/assayer-session-prompts.md Session 5。
读 docs/ux-design.md Screen 2（The Assay）。
读 docs/CONVENTIONS.md。

前置验证：确认 /change 1 已完成 —
- src/app/page.tsx 是 server component（不含 "use client"）
- src/components/landing-hero-input.tsx 存在
- 点击 "Test it" 导航到 /assay?idea=...

这是 Session 5 /change 2 of 3。用 /change 实现 Assay Page 重构：

### 现状（bootstrap 产物，需大幅重构）

`src/app/assay/page.tsx`（~541 行 monolith client component）。
数据流：自制 `streamText` + `specSections` + `SpecSection` 类型，显示 raw monospace text。
不使用 specReducer — `src/lib/spec-reducer.ts` 已存在（export specReducer, SpecState, SpecStreamEvent, initialSpecState）但从未被 import。
Signup modal 内嵌在此文件中（~100 行 Dialog 组件），基本 email + OAuth。
不读 URL searchParams、不使用 session_token、没有 edit mode、没有 regenerate、没有 preflight caution UI。

### 改动要点

1. 替换数据流：删除 `streamText`/`specSections`/`SpecSection` 类型及相关 state，切换到 `specReducer`（import from `@/lib/spec-reducer`）
2. URL searchParams 驱动：从 landing 传来的 `?idea=...&type=...&level=...` 读取并自动触发 SSE。新增 `upgrade_from` param 支持（Level upgrade flow）：当 `?upgrade_from=<experiment_id>` 存在时，显示 "Upgrading from L{level}" indicator，claim 时传递 upgrade_from 到 POST /api/spec/claim
3. Progressive rendering：用 SpecState 各字段（meta, cost, preflight, hypotheses, variants, funnel）驱动结构化卡片（不是 raw text block）
4. 提取 signup modal：将内嵌的 signup Dialog 代码（~100 行）提取为 `src/components/signup-gate.tsx`（基础版：保留现有 email + OAuth 功能），assay page 改为 `import SignupGate from "@/components/signup-gate"`
5. 新增：session_token cookie 管理、regenerate 按钮（传 regenerate_token）、preflight caution UI、edit mode
6. 这是重构，不是在旁边加代码 — 删除旧的 streaming 实现，用 specReducer-based 实现替换

### 目标结构

这是 Assayer 的核心 UX — spec 在最终布局中逐步 materialize。

两种模式：
- Creation mode（`?idea=...` 或无 query params，匿名可用）：调用 /api/spec/stream → 生成新 spec
- Edit mode（`?experiment=<id>&round=N&mode=edit`，需要 auth）：加载已有实验数据，bottleneck highlighted + AI 建议的修改预填。由 REFINE verdict return flow 触发。

#### Creation Mode

a. 调用 POST /api/spec/stream（SSE）
b. 使用 specReducer 累积 events
c. 页面布局 = 最终的 Review & Edit 布局，但初始为空/skeleton

Progressive rendering 顺序（来自 product-design.md Data Flow Timeline）：
- t=1s: meta → header renders（name, level, type）
- t=2s: cost → cost badge 出现
- t=3-8s: preflight → 4 个 dimension checks 逐个动画
- t=9s: preflight_opinion → AI opinion 文本 fade in
- t=10-18s: hypothesis → cards 逐个 fade in
- t=19-25s: variant → cards 填充
- t=26-28s: funnel → threshold rows
- t=29s: complete → "Create & Launch" 按钮激活

Generation 完成后：
- 所有字段显示 edit icon [e]（但 disabled，需要 auth）
- "Create & Launch" 按钮出现
- "Regenerate" 按钮出现（调用 /api/spec/stream，传递 regenerate_token = 上次 complete event 返回的 anonymous_spec_id，不消耗新的 rate limit quota）
- "WHAT HAPPENS NEXT" section

Pre-flight caution（ux-design.md）：
- 如果任何 preflight dimension 是 caution 或 fail
- 显示 AI Opinion section
- [Adjust idea & re-check] → 返回 landing（带 competition context）
- [Proceed anyway →] → 继续

点击 edit 或 "Create & Launch" → 触发 SignupGate modal（if unauthenticated）

#### Edit Mode（?experiment=<id>&round=N&mode=edit）

REFINE verdict return flow 触发此模式（Session 7 实现 return flow，本 session 构建 edit mode UI）。

a. Auth check: 必须已登录，否则重定向到 /lab
b. 数据加载: GET /api/experiments/:id — 返回 experiment + hypotheses + variants + latest round
c. Header: 显示 "Round {N} (editing)" indicator + experiment name
d. Bottleneck highlighting: bottleneck hypothesis card 显示 amber border + "bottleneck" badge
e. AI Suggestion panel: collapsed Accordion（shadcn/ui），内容从 experiment_decisions.reasoning 提取
f. 表单预填: 所有字段从已有数据预填
g. 操作: [Create & Launch] 创建新 round；[Regenerate] 不可用；edit icons 直接可用

npm run build 零错误。
```

**Prompt 3 of 3 — Signup Gate**（新对话）:

```
读 docs/assayer-session-prompts.md Session 5。
读 docs/ux-design.md Screen 3（Signup Gate）。
读 docs/assayer-product-design.md Section 2（TOTP 2FA）。
读 docs/CONVENTIONS.md。

前置验证：确认 /change 2 已完成 —
- src/components/signup-gate.tsx 存在（基础版）
- src/app/assay/page.tsx 使用 specReducer（import from @/lib/spec-reducer）
- src/app/assay/page.tsx import SignupGate from @/components/signup-gate

这是 Session 5 /change 3 of 3。用 /change 增强 Signup Gate：

### 现状（/change 2 已提取基础版，需增强）

`src/components/signup-gate.tsx` 已由 /change 2 从 assay page 中提取（基础版：email + OAuth）。
尚无 TOTP 2FA、无 quota check 错误处理、无 session_token claim 流程。
`src/app/signup/page.tsx` 和 `src/app/login/page.tsx` 作为独立全页注册/登录存在 — 保留不改。

### 改动要点

1. 增强 `src/components/signup-gate.tsx`（已存在基础版），不需要重新创建
2. 新增 TOTP 2FA enrollment：Supabase Auth MFA API（仅 email+password 注册后触发，OAuth 跳过）
3. 新增 quota check 错误处理：claim 返回 403 free_tier_limit 时，显示 upgrade/topup CTA
4. 新增 session_token claim 流程：登录后自动调用 POST /api/spec/claim { session_token }
5. 不修改独立 signup/login 页面

### 目标结构

Modal overlay（不是新页面），触发条件：未登录用户点击 edit 或 "Create & Launch"。

内容：
- "Pre-flight passed. Your experiment spec is ready."
- "Sign up to save this experiment and start testing."
- "Your free account includes 1 complete experiment."
- [Continue with Google]
- [Continue with GitHub]
- Email + password form
- "Already have an account? [Sign in]"

使用 Supabase Auth：
- Google OAuth（openid email profile）
- GitHub OAuth
- Email + password

TOTP 2FA 流程：
- Email+password 注册完成后，显示 TOTP 2FA enrollment 步骤
- 使用 Supabase Auth MFA API：supabase.auth.mfa.enroll({ factorType: 'totp' })
- 显示 QR code + manual secret entry
- 用户输入 6 位验证码确认 enrollment
- 后续每次 email+password 登录需要 TOTP 验证：supabase.auth.mfa.challengeAndVerify()
- OAuth 登录（Google/GitHub）跳过 TOTP
- 2FA enrollment UI 作为 Signup Gate modal 的 inline step，保持用户在 spec 上下文中

登录成功后：
a. 调用 POST /api/spec/claim { session_token }
   - claim 内部先调用 check_experiment_quota RPC 检查 Free tier 限制
   - 如果 quota 不足，返回 403 + { error: { code: 'free_tier_limit', message: '...' } }
   - 前端显示: "Free accounts include 1 experiment. [Top up $10 →] or [Upgrade to Pro →]"
b. 返回同一页面，edit icons 激活，"Create & Launch" 可用

session_token：browser-generated UUID，存在 cookie 中。用于关联匿名 spec。

npm run build 零错误。
```

---

### Session 6a — Build & Launch Flow

**目标**：实现 Launch page 的完整 7-phase 流程。

**输入**：Session 5 的 Landing/Assay/Signup

**输出**：
- Launch page（Screen 5: Build → Quality Gate → Deploy → Content Check → Walkthrough → Distribution Approval → Live）
- Mock realtime events（真实 Cloud Run Jobs 在 S9 实现）

**输出合约**（Session 6b 验证）：
```
src/app/launch/[id]/page.tsx → Launch page with 7-phase UI (Build → Quality Gate → Deploy → Content Check → Walkthrough → Distribution Approval → Live)
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/ux-design.md Screen 5（Build & Launch）。
读 docs/assayer-product-design.md Section 3（Flow 3: Build → Deploy → Distribute）。
读 docs/CONVENTIONS.md。

用 /change 实现 Launch page 重构：

### 现状（bootstrap 产物，需重构）

`src/app/launch/[id]/page.tsx`（~432 行 client component）。
当前：spec preview（stack, behaviors, variants, hypotheses 表格）+ quality gate dialog + deploy 按钮。
不是 7-phase 流程，没有 variant carousel、build logs、realtime events、walkthrough、distribution approval。
只有基本的 spec 审核 + 一键部署功能。

### 改动要点

1. **重构为 7-phase stepper/wizard**：替换当前的 spec preview + deploy 布局为多阶段流程 UI
2. **新增 Supabase Realtime 订阅**：exec:{execution_id} channel（mock events for now, Session 9 实现真实触发）
3. **新增 Content Check / Walkthrough / Distribution Approval phases**：当前页面完全没有这些
4. **保留 quality gate 逻辑概念**（已有 dialog），重构为 Phase B 的 UI 形态

## 1. Launch Page（/launch/[id]）— Screen 5

点击 "Create & Launch" 后进入此页面。流程 level-dependent：

L1: Build → Deploy → Content Check → Distribution Approval → Live
L2: Build → Quality Gate → Deploy → Walkthrough → Distribution Approval → Live
L3: Build → Quality Gate → Deploy → Walkthrough → Distribution Approval → Live

### Phase A: Build & Deploy

- 上方: variant carousel preview（live preview 原则）
- 下方: progress bar + step list
- 步骤: "Experiment saved" → "Landing page scaffolded (3 variants)" → "Deploying..."
- [View build logs] 折叠区域
- 使用 Supabase Realtime 订阅 exec:{execution_id} channel
- Event types: log, status, gate, progress（含 preview_url）

注意：Session 9 实现真正的 Cloud Run Jobs 触发。本 session 构建完整 UI，
使用 mock/stub 数据模拟 realtime events，确保 UI 流程完整。

### Phase B (L2/L3): Quality Gate

- 显示 behavior tests 状态: ok / testing / queued / failed
- Auto-fix loop UI: "AI is diagnosing..." → "Fixing..." → "Re-testing..."（最多 3 次 retry，显示 "retry 1/3"）
- Auto-fix 3 次失败后三个选项: [Simplify feature] [Skip feature] [Describe fix]
- **Build/deploy timeout**（>15 min 无进展）: 显示 inline warning "Build is taking longer than expected" + [Retry] + [View Logs] 按钮。
  检测方式: Realtime channel 15 分钟内无 progress event → frontend timer 触发 timeout UI。
  Retry: POST /api/skills/:id/cancel + POST /api/skills/execute（new execution）。

### Phase C (L1): Content Check

部署完成后显示 live preview + editable text:
- Headline [e], Subheadline [e], CTA [e], Pain points [e], Promise/Proof [e]
- 点击 [e] → inline text editor
- 编辑更新 variants 表（零 rebuild）
- 编辑过的字段显示 "(edited)" badge（inline, text-xs text-muted-foreground）
- Variant cross-contamination prevention（适用于 Content Check 和 Walkthrough）:
  保存任一 variant 的编辑后，显示 toast:
  "You edited {variant_name}. Review the other {N} variants too?"
  含 [Review] button → carousel 自动滚动到下一个 variant（防止 A/B contamination）
- "Looks good? [Continue to Distribution →]" / "[Review & edit content]"

### Phase D (L2/L3): Walkthrough

Golden path 步骤列表:
- 每步: description + [Open →]（新标签打开 live experiment）
- User 确认或报告问题
- 问题: text input + [Fix this →]（触发 micro /change）
- Variant cross-contamination prevention: 同 Content Check — 编辑任一 variant 后 toast 提醒 review 其他 variants + auto-scroll
- [Skip walkthrough — looks good]

### Phase E: Channel Setup (first-time only)

如果用户没有连接任何 distribution channel:
- RECOMMENDED (free): Twitter/X, Reddit, Email (Resend)
- PAID (Pro required): Google Ads, Meta Ads, Twitter Ads
- [Skip — I'll drive traffic myself]

### Phase F: Distribution Approval Gate

- AI 生成的分发计划: per-channel budget + creative preview
- [Preview Creative v] 展开显示 ad copy / tweet thread / reddit post
- "Google/Meta bill you directly — Assayer never touches your ad budget."
- [Edit Plan] [Launch Distribution →]

### Phase G: Distribution Live

- Channel 状态列表: ok/pending/failed
- "What happens now" section
- [Go to experiment →]

npm run build 零错误。
```

---

### Session 6b — Experiment Page + Change Request + Alerts

**目标**：实现实验主页面和 change request UI。

**输入**：Session 6a 的 Launch page

**输出**：
- Experiment page（Screen 6: Scorecard hero + traffic + live assessment + detail tabs）
- Change Request UI（natural-language change interface）
- Alert banners（7 alert types）
- Action button state changes

**输出合约**（Session 7 验证）：
```
src/app/experiment/[id]/page.tsx → Experiment page with scorecard hero + traffic + live assessment + detail tabs
src/components/change-request.*  → Change Request UI component
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/ux-design.md Screen 6（Experiment Page）。
读 docs/assayer-product-design.md Section 8（Alert System）。
读 docs/CONVENTIONS.md。

用 /change 实现 Experiment Page 重构：

### 现状（bootstrap 产物，需重构）

`src/app/experiment/[id]/page.tsx`（~558 行 client component）。
当前：基本 scorecard（funnel metrics 表格）+ hypotheses tab（status indicators）+ overview tab + change request dialog（type selector + budget/description inputs）。
缺少：traffic section（per-channel chart + budget bar）、live assessment section（bottleneck + projected verdict + "Analyze Now" guard clause）、7 种 alert banner、detail tabs（Variants/Distribution/Raw Data/History）。
Change request 是简化版 dialog，不是 natural-language change interface with AI classification + pricing。

### 改动要点

1. **重构 scorecard**：从简单表格改为 5-dimension progress bar + ratio + PASS/LOW/N/A + confidence bands
2. **新增 Traffic section**：per-channel mini bar chart + budget progress bar + [Pause All] / [Adjust]
3. **新增 Live Assessment section**：bottleneck identification + projected verdict + "Analyze Now" guard clause UI
4. **新增 Alert Banners**：7 种 alert types，从 experiment_alerts 表读取
5. **重构 Change Request**：替换简化 dialog 为 natural-language interface with AI classification + pricing display
6. **新增 detail tabs**：Variants / Distribution / Raw Data / History（在现有 Hypotheses tab 基础上扩展）

## 1. Experiment Page（/experiment/[id]）— Screen 6

用户每天回来看的主页面。

Content Check 编辑: 所有 level（L1/L2/L3）的 experiment page 上，variant text fields 都显示 [e] edit icons，支持 free inline editing（零 rebuild，直接更新 variants 表）。编辑过的字段显示 "(edited)" badge。这与 Launch page 的 Content Check phase 共享相同的 inline editor 组件。

结构（严格按照 ux-design.md 的 ASCII wireframe）：

Header: 名称 + status badge + Day X/Y + Level

=== FUNNEL SCORECARD ===（hero）
- 5 维度（REACH, DEMAND, ACTIVATE, MONETIZE, RETAIN）
- 每个: progress bar + ratio + PASS/LOW/N/A
- 包含 actual vs threshold 和 sample size
- Confidence bands: <30 insufficient, 30-100 directional, 100-500 reliable, 500+ high

=== TRAFFIC ===
- Total clicks / spend / avg CPC
- Per-channel mini bar chart（clicks, spend, CTR）
- Budget progress bar
- [Pause All] [Adjust v]

=== LIVE ASSESSMENT ===
- Bottleneck identification
- Best channel
- Projected verdict
- [Analyze Now] [Upgrade to L2] [Request Change]

[Upgrade to L2] onClick: 导航到 `/assay?idea=${encodeURIComponent(experiment.idea_text)}&type=${experiment.experiment_type}&level=${experiment.experiment_level + 1}&upgrade_from=${experiment.id}`。Assay page 检测 upgrade_from param → 显示 "Upgrading from L${level}" indicator。生成新 spec 后，POST /api/spec/claim { session_token, upgrade_from } → 新 experiment 带 parent_experiment_id，原 experiment 标记 completed（graduated）。仅在 experiment.experiment_level < 3 时显示此按钮。

[Analyze Now] guard clause UI: 当 guard 触发（total clicks < 100 或 experiment duration < 50% of estimated_days）时，不跳转到 verdict page。而是显示 inline dialog/toast，包含 directional signal（"Early signal: REACH looks strong, DEMAND needs more data"）+ sample size indicator + "Need ~X more clicks for a reliable verdict"。仅当 guard 通过时才跳转到 /verdict/[id]。

--- Details ---（折叠区域）
- [Hypotheses] [Variants] [Distribution] [Raw Data] [History]

Hypotheses tab 显示 per-hypothesis status（CONFIRMED / REJECTED / INCONCLUSIVE / BLOCKED / TESTING），来自 /iterate 结果写入 hypotheses 表的 status 字段。每个 hypothesis card 显示 status badge + 关联的 metric ratio。BLOCKED hypotheses 显示依赖关系链接。

## 2. Alert Banners

Alert banners（顶部，来自 experiment_alerts 表）：
- 7 种 alert type（product-design.md Section 8）
- 每种: one-line description + action buttons
- bug_auto_fixed: green-tinted banner（informational）

## 3. Change Request

[Request Change] 打开 natural-language change interface：

Before distribution（no traffic）:
- Text input: "What do you want to change?"
- AI analysis: impact list + classification + price
- [Apply Change $6] [Cancel]

During active experiment（traffic flowing）:
- Warning: "This experiment has been live for X days (Y clicks)."
- "Changing X will start a NEW ROUND because..."
- [Start Round 2 with this change →] [Cancel]

## 4. Action Button State Changes

Action buttons 根据 status 变化（来自 ux-design.md）：
- Active: [Pause] [Analyze Now] [Upgrade] [Request Change]
- Completed: [View Verdict] [Archive]
- Draft: [Deploy]

npm run build 零错误。
```

---

### [CP2] Checkpoint: UI Core

**验证范围**：Sessions 5-6b 的所有输出。

**检查项**：
1. `npm run build` 零错误
2. `npx tsc --noEmit` 零错误
3. `npm test` 通过
4. Landing page（/）渲染无错误
5. Assay page（/assay）SSE streaming 可用
6. Launch page（/launch/[id]）7-phase UI 完整（mock events）
7. Experiment page（/experiment/[id]）scorecard + traffic + assessment + details tabs 渲染
8. Signup Gate modal 触发正常
9. Alert banners 渲染（mock data）
10. Change Request UI 打开/关闭正常
11. 所有页面无 console errors
12. **数据合约形状验证**（防止 UI↔API 累积偏移）:
    UI 组件当前使用 mock 数据。验证 mock 数据的 TypeScript 类型与 Session 3 创建的 API route 返回类型匹配：
    - Scorecard mock → `GET /api/experiments/:id/metrics` 返回的 `experiment_metric_snapshots` 行结构
    - Alert banners mock → `GET /api/experiments/:id/alerts` 返回的 `experiment_alerts` 行结构
    - Experiment card mock → `GET /api/experiments` 返回的 `experiments` 行结构
    如果 mock shape 与 DB schema 不匹配（字段名、类型、嵌套结构），修正 mock 以保持合约一致。
13. `quality: production` — 已实现 behaviors (b-01~b-15) 的 `tests` 条目：UI 渲染类由 Playwright smoke/funnel 覆盖，交互逻辑类有 spec test assertion。缺失的覆盖必须补上。

**输出**：CP2 verification report。失败项必须修复后才能进入 Phase 4。

**Prompt**:

```
执行 [CP2] Checkpoint: UI Core。

验证范围：Sessions 5-6b 的所有输出。

步骤：

1. 运行自动化检查：
   - `npm run build`（零错误）
   - `npx tsc --noEmit`（零错误）
   - `npm test`（全部通过）
   如有失败，修复后重新运行，最多 3 次。

2. UI 渲染验证：
   确认以下页面渲染无错误且无 console errors：
   - Landing page（/）
   - Assay page（/assay）— SSE streaming 可用
   - Launch page（/launch/[id]）— 7-phase UI 完整（mock events）
   - Experiment page（/experiment/[id]）— scorecard + traffic + assessment + details tabs
   - Signup Gate modal 触发正常
   - Alert banners 渲染（mock data）
   - Change Request UI 打开/关闭正常

3. **数据合约形状验证**（防止 UI 先于 backend 导致的 mock↔schema 偏移）：
   UI 组件当前使用 mock 数据（真实 backend 在 S11 才连接）。验证 mock 数据结构与 Session 3 的 DB schema 一致：
   - 读取 `supabase/migrations/` 中的 `experiment_metric_snapshots` 表定义，对比 Scorecard 组件的 mock props
   - 读取 `experiment_alerts` 表定义，对比 Alert Banner 组件的 mock props
   - 读取 `experiments` 表定义，对比 Lab Card 组件的 mock props
   - 特别检查: jsonb 字段（channel_metrics, distribution_roi）的 mock shape 与 Session 11 即将写入的结构一致
   如发现偏移（字段名不匹配、类型错误、嵌套结构不同）：修正 mock 并确保 TypeScript 类型通过 `npx tsc --noEmit`

4. behavior.tests 覆盖验证（quality: production）：
   读 experiment/experiment.yaml 中 behaviors b-01 到 b-15（UI behaviors）。
   - UI 渲染类条目（"page renders", "content displays"）：确认 Playwright smoke/funnel test 覆盖
   - 交互逻辑类条目（"navigation occurs", "modal triggers"）：确认有 spec test 或 Playwright assertion
   缺失的覆盖：补上对应测试。补完后重新运行 npm test 确认通过。

5. 生成 checkpoint report 写入 docs/cp2-report.md。

所有检查项通过后，报告结果。失败项必须修复后才能进入 Phase 4。
```

---

## Phase 4: Supporting Pages + Billing

### Session 7 — Lab + Verdict + Compare + Settings

**目标**：实现剩余四个页面。

**输入**：Session 6 的 Experiment Page

**输出**：
- Lab page（Screen 8: portfolio view）
- Verdict page（Screen 7: full-screen ceremony）
- Compare page（multi-experiment comparison）
- Settings page（Screen 9）
- REFINE / PIVOT return flows

**输出合约**（Session 8 验证）：
```
src/app/lab/page.tsx            → Lab page with portfolio view (grouped by state)
src/app/verdict/[id]/page.tsx   → Verdict page with 4 verdict types (SCALE/KILL/REFINE/PIVOT)
src/app/compare/page.tsx        → Compare page with side-by-side comparison
src/app/settings/page.tsx       → Settings page with 4 sections (Account, Connected Accounts, Distribution Channels, Plan & Billing)
src/app/api/experiments/compare/route.ts → GET handler
src/app/api/experiments/[id]/metrics/export/route.ts → GET handler (CSV download)
src/components/portfolio-insight-card.tsx             → exports PortfolioInsightCard component
src/components/budget-allocation.tsx                  → exports BudgetAllocation component (sliders)
src/app/api/portfolio/insight/route.ts               → exports GET handler
src/app/api/portfolio/insight/[id]/apply/route.ts    → exports POST handler
src/app/api/portfolio/insight/[id]/dismiss/route.ts  → exports POST handler
src/app/api/portfolio/budget/route.ts                → exports GET handler
src/app/api/portfolio/budget/allocate/route.ts       → exports POST handler
```

**Prompt 1 of 3 — Verdict Page + Return Flows**（新对话）:

```
读 docs/assayer-session-prompts.md Session 7 的「输入合约验证」和前序 session 的「输出合约」，执行 preamble 验证。
读 docs/ux-design.md Screen 7（Verdict）、Screen 7a（Return Flows）。
读 docs/CONVENTIONS.md。

这是 Session 7 /change 1 of 3。用 /change 实现 Verdict Page + Return Flows：

### 现状（bootstrap 产物，需重构）

`src/app/verdict/[id]/page.tsx`（~411 行）。当前：verdict hero display + hypothesis results table + distribution ROI breakdown + channel metrics table + recommendation section。
缺少：4 种 verdict 的差异化 emotional treatment（SCALE/KILL/REFINE/PIVOT 各有不同 UI 风格）、post-mortem tab、return flows（REFINE → /assay edit mode, PIVOT → / landing with pre-fill）、status transition（verdict_ready → completed）、CSV data export。

### 改动要点

1. **差异化 verdict treatment**：SCALE（celebratory）, KILL（respectful + "you saved 3 months"）, REFINE（actionable + bottleneck highlight）, PIVOT（suggestive + pivot direction）
2. **新增 post-mortem tab**（`?tab=postmortem`）：final scorecard + per-channel ROI + AI analysis + round timeline + CSV download
3. **新增 return flows**：REFINE → create experiment_rounds row → redirect /assay?experiment=...&mode=edit; PIVOT → archive + create child experiment → redirect / with pivot suggestion
4. **新增 status transition**：page mount 时 PATCH experiment status → completed
5. **新增 CSV export API**：GET /api/experiments/:id/metrics/export

### 目标结构

**这是 Assayer 最重要的页面 — full-screen moment。**

四种 verdict，每种不同的 emotional treatment：

SCALE: "↑ SCALE" 大字 + 5 维度 ratio + DISTRIBUTION ROI + "Recommendation for L2" + [Upgrade to L2 →] [View Full Report]
KILL: "✕ KILL" + "You saved approximately 3 months of building. This is a good outcome." + [Archive & Start New Experiment →] [View Post-Mortem]
REFINE: "~ REFINE" + bottleneck dimension highlighted + [Apply Changes & Re-test →] [Upgrade to L2 →] [View Full Report]
PIVOT: "<-> PIVOT" + "Consider: Change target audience / Reframe value prop / Test different channels" + [Start New Experiment with Pivot →] [View Post-Mortem] [Archive]

Status Transition: verdict_ready → completed（page mount 时 PATCH experiment status）

Post-Mortem（KILL 和 PIVOT only）: 实现为 ?tab=postmortem — Final Scorecard + Per-Channel ROI Table + AI Analysis + Round Timeline + Data Export [Download CSV]

Return Flows:
- REFINE: 创建 experiment_rounds row → status → draft → redirect /assay?experiment=...&round=N+1&mode=edit
- PIVOT: archive + create child experiment → redirect /?idea=...&pivot_from=experimentId
- UPGRADE（SCALE/REFINE verdict 的 [Upgrade to L2]）: 导航到 `/assay?idea=${encodeURIComponent(experiment.idea_text)}&type=${experiment.experiment_type}&level=${experiment.experiment_level + 1}&upgrade_from=${experiment.id}`。与 Experiment page 的 [Upgrade to L2] 按钮行为一致（见 Session 6b）。仅在 experiment_level < 3 时显示。

npm run build 零错误。
```

**Prompt 2 of 3 — Lab Page + Lineage**（新对话）:

```
读 docs/assayer-session-prompts.md Session 7。
读 docs/ux-design.md Screen 8（Lab）。
读 docs/CONVENTIONS.md。

前置验证：确认 /change 1 已完成 — src/app/verdict/[id]/page.tsx 包含 4 种 verdict treatment + return flows。

这是 Session 7 /change 2 of 3。用 /change 实现 Lab Page：

### 现状（bootstrap 产物，需重构）

`src/app/lab/page.tsx`（~283 行）。当前：experiment grid with search + filtering + status badges + verdict display + conversion rate indicators + click navigation。
缺少：按状态分组（RUNNING / VERDICT READY / COMPLETED）、"Robinhood approach" card 信息密度（ONE number — bottleneck ratio）、empty state copy（ux-design.md 明确要求的文案）、REFINE round lineage badge、PIVOT lineage subtitle。

### 改动要点

1. **按状态分组**：RUNNING（bottleneck ratio + Day X/Y）, VERDICT READY（prominent cue + [View Verdict →]）, COMPLETED（compact + verdict badge）
2. **Card 信息密度重构**：每张 card ONE number — bottleneck ratio（不是当前的多指标 grid）
3. **Empty state**：使用 ux-design.md 指定的文案
4. **新增 lineage visualization**：REFINE rounds badge + PIVOT "Pivoted from" subtitle

### 目标结构

Portfolio view — experiments grouped by state:
- RUNNING: card 显示 bottleneck ratio + Day X/Y + ON TRACK/LOW + channel count + spend
- VERDICT READY: prominent visual cue + [View Verdict →]
- COMPLETED: compact cards with verdict badge

Empty state: "No experiments yet." + "Every founder has ideas. The difference is knowing which one to build." + [Test your first idea →]

Card 信息密度（Robinhood approach）: 每张 card ONE number — bottleneck ratio。
[+ New Idea] button → 导航到 Landing page。

Lineage visualization:
- REFINE rounds: Lab card 右上角 "Round N" badge + dropdown 列出所有 rounds
- PIVOT lineage: Lab card 名称下方 "Pivoted from {parent_name}" subtitle
- 视觉分组: REFINE rounds 缩进或共享 header。PIVOT children 独立 card + lineage subtitle。

npm run build 零错误。
```

**Prompt 3 of 3 — Compare + Settings + API Routes**（新对话）:

```
读 docs/assayer-session-prompts.md Session 7。
读 docs/ux-design.md Screen 9（Settings）、Experiment Comparison。
读 docs/CONVENTIONS.md。

前置验证：确认 /change 1-2 已完成 — verdict page 有 return flows, lab page 有 lineage visualization。

这是 Session 7 /change 3 of 3。用 /change 实现 Compare + Settings + API Routes：

### 现状（bootstrap 产物，需重构）

`src/app/compare/page.tsx`（~391 行）：基本 A/B selectors + verdict comparison cards + funnel metrics + progress bars。缺少 Pro/Team gate。
`src/app/settings/page.tsx`（~416 行）：account section + notifications toggle + OAuth connections + billing section。缺少 distribution channels OAuth（独立于 login OAuth）、plan comparison table、invoice 查看。

### 改动要点

1. **Compare page**：添加 Pro/Team plan gate + API route（GET /api/experiments/compare?ids=...）
2. **Settings page**：4 sections 重构 — Account, Connected Accounts (login OAuth), Distribution Channels (distribution OAuth, 独立!), Plan & Billing（inline comparison table + Stripe portal + invoices）
3. **PIVOT return flow landing page integration**：检测 `?pivot_from=` query param，显示 pivot context

### 目标结构

Compare Page（/compare）:
- Side-by-side experiment comparison（2+ experiments）
- 表格: experiment name × dimension ratios, Verdict, Confidence, Cost, Time, Best channel
- Assayer Score row (★ XX) + CPA row + AI recommendations section（如 product-design.md Portfolio Intelligence 描述）
- **[Export CSV] 按钮**（ux-design.md 明确要求）: 导出 comparison table 数据为 CSV 文件。
  实现: 前端生成 CSV（`Blob` + `URL.createObjectURL` + `<a download>`），不需要独立 API route。
  CSV 列: Experiment Name, Score, REACH, DEMAND, ACTIVATE, MONETIZE, RETAIN, Verdict, Confidence, Ad Spend, CPA, Best Channel
- Pro/Team plan only
- API: GET /api/experiments/compare?ids=uuid1,uuid2,uuid3

Settings Page（/settings）— 4 sections:
- ACCOUNT: Email display, [Change Password] button → inline form（current password + new password + confirm）→ `supabase.auth.updateUser({ password: newPassword })`。成功后显示 toast "Password updated"。仅对 email+password 用户显示（OAuth-only 用户隐藏此按钮）。
- CONNECTED ACCOUNTS（login OAuth）: Google, GitHub — [Disconnect]
- DISTRIBUTION CHANNELS（distribution OAuth — 独立于 login OAuth!）: Organic (Twitter/X, Reddit, Resend) + Paid (Google Ads, Meta Ads, Twitter Ads)
- PLAN & BILLING: Current plan + pool usage + PAYG balance + plan comparison table (Free/PAYG/Pro/Team) + [Manage Subscription] → Stripe Portal + [View Invoices]
  Plan comparison table 必须包含 ux-design.md 的完整行（与 Landing pricing 一致）: Spec generation, Creates, Modifications, Content edits, Auto-fix, Hosting, Paid distribution, Portfolio Intelligence, **Team seats**（1/1/1/5）, **Priority build**（--/--/--/Yes）, Overage。
  Team seats 和 Priority build 是 display-only 行项（MVP 不实现 multi-user invite 或 priority queue 功能）。

API Routes:
- GET /api/experiments/compare?ids=... — side-by-side comparison data
- GET /api/experiments/:id/metrics/export — CSV download（Post-Mortem 的 [Download CSV]）

PIVOT Return Flow Landing Integration:
- Landing page 检测 `?pivot_from=` query param
- 显示 "Pivoted from: {parent name}. AI suggestion: {pivot direction}"

## Portfolio Intelligence UI

### Lab Enhancement

1. RUNNING experiment cards:
   - Add `★ {assayer_score}` display in top-right corner of each card
   - Add compressed dimension ratios: `R {reach}x D {demand}x M {monetize}x`
   - Sort RUNNING group by assayer_score DESC (highest first)
   - Status label derived from score: 80-100 ON TRACK, 60-79 PROMISING, 40-59 LOW !, 20-39 DANGER, 0-19 CRITICAL
   - Score is NULL when no data → show "—" and sort last

2. AI Insight card:
   - Conditionally render between RUNNING and VERDICT READY groups
   - Visible when: user has 2+ RUNNING experiments AND portfolio_insights has a non-dismissed, non-applied record
   - Fetch from GET /api/portfolio/insight
   - Display: numbered recommendations from insight_json
   - [Apply suggestions ->] → POST /api/portfolio/insight/:id/apply → refresh Lab
   - [Dismiss] → POST /api/portfolio/insight/:id/dismiss → hide card
   - Styled with gold accent border (using existing gold design token)
   - Plan gate: hidden for Free/PAYG users (check user plan)

3. Budget tab (Team plan only):
   - Add [Experiments] [Budget] tab switcher in Lab header
   - [Budget] tab visibility: Team plan users only
   - Budget overview: total allocated / total available with progress bar
   - Table: Experiment | Spent | Remaining | Score | Status with spend progress bars
   - AI Budget Optimizer: CURRENT → RECOMMENDED columns with reasoning text
   - [Apply Rebalance ->] → POST /api/portfolio/budget/allocate
   - [Customize] expands linked percentage sliders constrained to 100%
   - Fetch from GET /api/portfolio/budget

### Compare Enhancement

4. Add Score row (★ XX) as first data row in comparison table
5. Add CPA row ($ per activation) after existing metrics
6. Add AI RECOMMENDATION section below table:
   - Fetch latest portfolio_insight
   - Display top_experiment highlight + numbered recommendations
   - [Apply All ->] [Apply #1 only] [Dismiss] buttons

### API Routes (implement alongside UI)

7. `GET /api/portfolio/insight` — return latest active insight for user
8. `POST /api/portfolio/insight/:id/apply` — execute recommendations (Pro+ gate)
9. `POST /api/portfolio/insight/:id/dismiss` — mark dismissed
10. `GET /api/portfolio/budget` — return budget allocation (Team gate)
11. `POST /api/portfolio/budget/allocate` — apply custom allocation (Team gate)

npm run build 零错误。
```

---

### Session 8 — Billing + Operations

**目标**：实现完整的 billing 系统 — Stripe integration、operation classifier、billing gate、PAYG + subscription。

**输入**：Session 7 的页面 + Session 3 的 user_billing / operation_ledger 表

**输出**：
- Stripe integration（subscriptions + PAYG checkout + portal）
- Operation classifier（Haiku）
- Billing gate（authorize before execution）
- Completion handler
- Webhook handler（5 event types）
- Billing API routes

**输出合约**（Session 9a 验证）：
```
src/lib/operation-classifier.ts                → export function classifyOperation
src/app/api/operations/authorize/route.ts      → POST handler returning { operation_id, price, type, billing_source }
src/app/api/operations/complete/route.ts       → POST handler
src/app/api/billing/subscribe/route.ts         → POST handler
src/app/api/billing/topup/route.ts             → POST handler
src/app/api/billing/portal/route.ts            → POST handler
src/app/api/billing/usage/route.ts             → GET handler
src/app/api/webhooks/stripe/route.ts           → POST handler with signature verification
src/app/api/portfolio/insight/route.ts         → plan gate: Pro+ (Free/PAYG returns null)
src/app/api/portfolio/budget/route.ts          → plan gate: Team only (403 for non-Team)
```

**Prompt 1 of 2 — Billing Core**（新对话）:

```
读 docs/assayer-session-prompts.md Session 8 的「输入合约验证」和前序 session 的「输出合约」，执行 preamble 验证。
读 docs/assayer-product-design.md Section 2（Billing & Metering Architecture）。
读 docs/ux-design.md Pricing & Plans section。
读 docs/CONVENTIONS.md。

### 现状（bootstrap + CP1 产物，需增强）

已有 billing routes:
- `src/app/api/billing/subscribe/route.ts`：基本 Stripe Checkout session（subscription mode），已有 rate limiting
- `src/app/api/billing/topup/route.ts`：基本 PAYG top-up checkout，已有 $10-$500 validation
- `src/app/api/billing/portal/route.ts`：基本 Stripe portal redirect
- `src/app/api/billing/status/route.ts`：读取 user_billing
- `src/app/api/webhooks/stripe/route.ts`：处理 5 种 event types（checkout.session.completed, subscription.created/updated/deleted, invoice.payment_failed），已有 signature verification

CP1 新增: `src/app/api/skills/route.ts` 有基本 billing check（plan != pro && balance <= 0 → 403）。

缺少: operation classifier（Haiku）、billing gate（authorize/complete 流程）、token budgets、pool counter management、usage API、hosting fee cron、PAYG→Pro conversion ladder。

### 改动要点

1. **新建** `src/lib/operation-classifier.ts`：Haiku classifier（全新文件）
2. **新建** `src/app/api/operations/authorize/route.ts` 和 `complete/route.ts`：billing gate 流程（全新文件）
3. **增强现有 billing routes**：subscribe 添加 Pro/Team price ID support；webhook 添加 pool counter reset on period change
4. **新建** `src/app/api/billing/usage/route.ts`：pool usage summary（全新文件）
5. **新建** `/api/cron/hosting-billing`：monthly hosting fee cron（全新文件）
6. **保留现有 skills route 的基本 billing check**（CP1 产物），authorize route 提供更完整的替代

这是 Session 8 /change 1 of 2。用 /change 实现 billing core：

## 1. Operation Classifier

创建 `src/lib/operation-classifier.ts`:
- Model: Haiku 4.5（~$0.001/call）
- Input: skill name + user description + affected behaviors
- Output: { type: "change" | "small_fix", confidence, reasoning }
- confidence < 0.7 → default to "change"（protects margin）
- 不需要 classify: creates（level known）, spec gen（always free）

## 2. Billing Gate

POST /api/operations/authorize:
a. 接收: { experiment_id, skill_name, description? }
b. Classify operation（if applicable）
c. 确定价格（product-design.md PAYG pricing table）:
   - Spec generation: Free
   - Create L1: $10, L2: $15, L3: $25
   - Change: $6, Small fix: $2
   - Content edit: Free, Auto-fix: Free
d. 检查 billing source（关键代码锚点）:
   ```typescript
   // Billing source resolution order
   const billing = await supabase.from('user_billing').select('plan, payg_balance_cents, creates_used, modifications_used, pool_resets_at, stripe_subscription_id, subscription_status').eq('user_id', user.id).single();

   // Past-due gate: block pool access for subscribers with failed payments
   if (billing.subscription_status === 'past_due') {
     // Allow PAYG-funded operations (user's own prepaid balance), block pool access
     // This incentivizes payment resolution while not completely locking out paying users
     if (billing.payg_balance_cents >= priceCents) return { billing_source: 'payg', price_cents: priceCents };
     return NextResponse.json({ error: { code: 'subscription_past_due', message: 'Your subscription payment failed. Please update your payment method or top up your PAYG balance.' } }, { status: 402 });
   }

   // Free tier = payg plan + zero balance + no subscription
   const isFree = billing.plan === 'payg' && billing.payg_balance_cents === 0 && !billing.stripe_subscription_id;

   if (isFree) {
     // Free tier: only spec_gen (unlimited) and 1 lifetime create allowed
     if (operationType === 'spec_gen') return { billing_source: 'free', price_cents: 0 };
     const quota = await supabase.rpc('check_experiment_quota', { p_user_id: user.id });
     if (!quota.allowed) return NextResponse.json({ error: { code: 'free_tier_limit', message: quota.message } }, { status: 403 });
     return { billing_source: 'free', price_cents: 0 }; // first experiment is free
   }

   // Subscriber: check pool
   if (billing.plan === 'pro' || billing.plan === 'team') {
     const poolLimits = { pro: { creates: 3, mods: 15 }, team: { creates: 10, mods: 60 } };
     const limits = poolLimits[billing.plan];
     if (isCreate && billing.creates_used < limits.creates) return { billing_source: 'pool', price_cents: 0 };
     if (isMod && billing.modifications_used < limits.mods) return { billing_source: 'pool', price_cents: 0 };
     // Overage: fall through to PAYG (Team gets 10% discount per ux-design.md pricing table)
   }

   // PAYG: check balance (Team overage at 90% of PAYG rates)
   const overagePriceCents = billing.plan === 'team' ? Math.round(priceCents * 0.9) : priceCents;
   if (billing.payg_balance_cents >= overagePriceCents) return { billing_source: 'payg', price_cents: overagePriceCents };

   // Insufficient balance
   return NextResponse.json({ error: { code: 'insufficient_balance', message: `Top up at least $${(priceCents / 100).toFixed(2)}` } }, { status: 402 });
   ```
e. 创建 operation_ledger row（status: authorized, token_budget）
f. Token budgets: Create L1 6M, L2 10M, L3 16M, Change 5M, Small fix 1.5M
g. 返回: { operation_id, price, type, billing_source }

## 3. Completion Handler

POST /api/operations/complete:
a. 接收: { operation_id, actual_tokens_used, status }
b. 更新 operation_ledger（actual cost, status）
c. Subscriber: decrement pool counter（creates_used or modifications_used）
   ```typescript
   // Atomic pool decrement
   await supabase.from('user_billing')
     .update({ [isCreate ? 'creates_used' : 'modifications_used']: billing[isCreate ? 'creates_used' : 'modifications_used'] + 1 })
     .eq('user_id', user.id);
   ```
d. PAYG: 使用 Session 3 创建的 `decrement_payg_balance` RPC（原子递减，防止竞态）:
   ```typescript
   const { data, error } = await supabase.rpc('decrement_payg_balance', {
     p_user_id: user.id,
     p_amount_cents: priceCents,
   });
   if (error) { /* handle insufficient balance — should not happen if authorize was called first */ }
   ```
e. PostHog server event: skill_cost { billed, actual_cost, margin_pct }

## 4. Stripe Integration

### Subscriptions
POST /api/billing/subscribe:
- 创建 Stripe Checkout session（subscription mode）
- Products: Pro（$99/mo, STRIPE_PRO_PRICE_ID）, Team（$299/mo, STRIPE_TEAM_PRICE_ID）

### PAYG Top-up
POST /api/billing/topup:
- Stripe Checkout session（one-time payment）
- Amount: $10-$500

### Customer Portal
POST /api/billing/portal:
- Stripe Customer Portal session URL
- 用于 subscription management, invoices, payment method

### Usage
GET /api/billing/usage:
- Current period summary: creates_used, modifications_used, payg_balance, pool_resets_at

## 5. Stripe Webhooks

POST /api/webhooks/stripe:
签名验证（STRIPE_WEBHOOK_SECRET）

**Idempotency**: Stripe 重试 webhook 最多 3 次。每次处理前用 event.id 做幂等性检查：
```typescript
// 使用 Supabase upsert — 如果 event.id 已存在则跳过
const { error } = await supabase.from('stripe_webhook_events')
  .insert({ event_id: event.id, event_type: event.type, processed_at: new Date().toISOString() })
  .onConflict('event_id');
if (error?.code === '23505') return NextResponse.json({ received: true }); // duplicate, skip
```
`stripe_webhook_events` 表加入 Session 3 PR2 migration（纯 infra 表，不计入 19 张 core tables）：
```sql
CREATE TABLE stripe_webhook_events (
  event_id text PRIMARY KEY,
  event_type text NOT NULL,
  processed_at timestamptz NOT NULL DEFAULT now()
);
-- Cleanup: cron/cleanup route 同时清理 > 30 天的 webhook events
```

处理 5 种 event types:

a. checkout.session.completed:
   - 判断是 subscription 还是 topup（metadata 区分）
   - Subscription: 更新 user_billing plan + stripe IDs
   - Topup: 增加 payg_balance_cents

b. customer.subscription.created:
   - 初始化 pool counters（Pro: 3 creates + 15 mods; Team: 10 + 60）

c. customer.subscription.updated:
   - 如果 current_period_start 变化 → reset pool counters
   - 处理 plan upgrade/downgrade

d. customer.subscription.deleted:
   - plan → 'payg', subscription_status → 'canceled'

e. invoice.payment_failed:
   - subscription_status → 'past_due'

npm run build 零错误。
```

**Prompt 2 of 2 — Pricing UX Integration**（新对话）:

```
读 docs/assayer-session-prompts.md Session 8。
读 docs/ux-design.md Pricing & Plans section。
读 docs/CONVENTIONS.md。

前置验证：确认 /change 1 已完成 —
- src/lib/operation-classifier.ts 存在
- src/app/api/operations/authorize/route.ts 存在
- src/app/api/operations/complete/route.ts 存在

### 现状（/change 1 已完成 billing core）

Billing core 已实现：operation classifier, authorize/complete flow, enhanced webhooks, hosting fee cron。
Experiment page（`src/app/experiment/[id]/page.tsx`，Session 6b 重构后）和 Change Request 组件尚未集成 pricing 显示。
Settings 页面（Session 7 重构后）的 billing section 需要与 usage API 对接。

### 改动要点

1. **增量修改 experiment page**：footer 添加 pool usage bar（GET /api/billing/usage）
2. **增量修改 change request 组件**：添加 classification + price + quota display（POST /api/operations/authorize preview）
3. **新增** near quota exhaustion warning + upgrade CTA
4. **新增** PAYG→Pro conversion ladder prompt

这是 Session 8 /change 2 of 2。用 /change 实现 pricing UX integration：

## 6. Pricing UX Integration

在 experiment page 和 change request UI 中集成 pricing 显示：
- Pre-modification: classification + price + remaining quota
- Experiment page footer（subscriber only）: "Modifications: 11/15 used this month"
- Near quota exhaustion: warning + upgrade CTA
- Free operations: no cost indicator

修改 Session 6 创建的文件（增量修改）：
a. src/app/experiment/[id]/page.tsx — footer 添加 pool usage bar（GET /api/billing/usage）
b. Change Request 组件 — 添加 classification + price + quota display（POST /api/operations/authorize preview）
c. Near quota exhaustion 时显示 warning banner + [Upgrade to Pro] CTA

## 7. Hosting Fee

每个 active experiment 收取 $5/mo hosting fee（Vercel/Railway 运行成本）:
- Free plan: 30 天免费，之后 auto-pause（experiment status → paused, distribution stopped）
- PAYG: 从 payg_balance_cents 中按月扣除
- Pro: 3 个 active experiments 包含在 $99/mo 中，超出部分 $5/mo each
- Team: 10 个 active experiments 包含在 $299/mo 中，超出部分 $5/mo each
- **实现方式**: 创建 Vercel Cron `/api/cron/hosting-billing`（monthly, 1st of month 00:00 UTC）:
  1. Query all users with active experiments (status IN ('active', 'verdict_ready'))
  2. For each user, count active experiments
  3. Determine included hosting slots: Free=1 (30 days only), PAYG=0, Pro=3, Team=10
  4. For Free tier: if experiment.started_at + 30 days < now() → auto-pause (status='paused', distribution stopped) + notification
  5. For overage experiments (count > included): charge $5/mo per overage experiment
     - PAYG: `supabase.rpc('decrement_payg_balance', { p_user_id, p_amount_cents: overageCount * 500 })`
     - Team: charge at 90% rate ($4.50/mo per overage experiment)
     - If insufficient balance: send email warning, auto-pause after 7 days
  6. PostHog server event: hosting_billing { user_id, active_count, included, overage_count, charged_cents }
- Auto-pause 前 7 天发送 email warning（复用 notification trigger 5 的 budget_alert 模板）
- 将此 cron 添加到 vercel.json 的 crons 配置中

## 8. PAYG→Pro Conversion Ladder

追踪用户累计月 PAYG 花费，当 spend > $90/mo 时 surface upgrade prompt:
- 在 experiment page footer 和 billing usage page 显示:
  "You spent $92 this month on PAYG. Pro is $99/mo with 3 creates + 15 modifications included."
- PostHog server event: payg_upgrade_prompt_shown { monthly_spend_cents, plan: 'payg' }
- 计算逻辑: SUM(operation_ledger.price_cents) WHERE created_at >= current_period_start AND user_id = X AND status = 'completed'

Environment variables 需要:
- STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY
- STRIPE_WEBHOOK_SECRET
- STRIPE_PRO_PRICE_ID, STRIPE_TEAM_PRICE_ID

## Portfolio Intelligence Billing Gates

Add plan-based access control for portfolio features:

1. AI Insight card: visible only for Pro and Team plans
   - GET /api/portfolio/insight: return null for Free/PAYG
   - POST /api/portfolio/insight/:id/apply: reject with 403 for Free/PAYG

2. Budget tab: visible only for Team plan
   - GET /api/portfolio/budget: reject with 403 for non-Team
   - POST /api/portfolio/budget/allocate: reject with 403 for non-Team

3. Assayer Score on Lab cards: visible for ALL plans (no gate)

4. Update the plan comparison data to include "Portfolio Intelligence" row:
   - Free: --
   - PAYG: --
   - Pro: Score + AI Insight
   - Team: Score + AI Insight + Budget Optimizer

npm run build 零错误。
```

---

### [CP3] Checkpoint: Full UI + Billing

**验证范围**：Sessions 5-8 的所有输出。

**检查项**：
1. `npm run build` 零错误
2. `npx tsc --noEmit` 零错误
3. `npm test` 通过
4. 所有 8 个页面渲染无错误（landing, assay, launch, experiment, verdict, lab, compare, settings）
5. Billing API routes 返回正确 HTTP status：
   - `POST /api/operations/authorize` → 200 with { operation_id, price }
   - `POST /api/billing/subscribe` → redirect to Stripe Checkout
   - `GET /api/billing/usage` → 200 with usage data
6. Stripe webhook handler signature 验证正常（test mode）
7. Settings 页面 4 sections 完整
8. Verdict page 4 种 verdict 类型渲染正确
9. Lab page 空状态 + 有数据状态渲染
10. Compare page Pro/Team gate 生效 + [Export CSV] 按钮存在
11. Settings plan comparison table 包含完整行（特别检查 Team seats=5, Priority build=Yes 行存在）
12. **数据合约一致性**: 验证 Session 8 的 billing API 返回类型与 Session 6b/7 的 UI 消费类型一致：
    - `GET /api/billing/usage` 返回的 pool counters 与 experiment page footer 的 "Modifications: X/Y" 显示匹配
    - `POST /api/operations/authorize` 返回的 `{ operation_id, price, type, billing_source }` 与 Change Request 组件消费一致
    - Verdict page 的 distribution ROI 显示组件预期的 jsonb shape 与 `experiment_decisions.distribution_roi` 列结构匹配
13. `quality: production` — 已实现 behaviors (b-01~b-18, b-22~b-25) 的 `tests` 条目均有对应 spec test 或 Playwright assertion。跳过 b-19~b-21（system behaviors，Session 11 实现）。特别检查 payment flows (b-22, b-23, b-25) 有深度测试（不只是 auth guard）。

**输出**：CP3 verification report。失败项必须修复后才能进入 Phase 5。

**Prompt**:

```
执行 [CP3] Checkpoint: Full UI + Billing。

验证范围：Sessions 5-8 的所有输出。

步骤：

1. 运行自动化检查：
   - `npm run build`（零错误）
   - `npx tsc --noEmit`（零错误）
   - `npm test`（全部通过）
   如有失败，修复后重新运行，最多 3 次。

2. UI + Billing 验证：
   - 确认 8 个页面渲染无错误
   - 确认 Billing API routes 返回正确 HTTP status
   - 确认 Stripe webhook handler signature 验证正常
   - 确认 Settings/Verdict/Lab/Compare 页面功能完整
   - 确认 Compare page 有 [Export CSV] 按钮
   - 确认 Settings plan comparison table 包含完整行（Team seats=5, Priority build=Yes）

3. **数据合约一致性验证**（Session 8 新增 billing 数据 → UI 消费验证）：
   - `GET /api/billing/usage` 返回的 `{ creates_used, modifications_used, payg_balance_cents, pool_resets_at }` → experiment page footer 的 pool usage 显示匹配
   - `POST /api/operations/authorize` 返回的 `{ operation_id, price_cents, type, billing_source }` → Change Request 组件的 price display 匹配
   - Verdict page 的 Distribution ROI 组件预期的 `distribution_roi` jsonb shape 与 `experiment_decisions` 表列结构一致（特别验证 `per_channel` array、`best_channel` string、`total_spend_cents` integer 等字段）
   如发现偏移：修正 UI 或 API 确保两端类型一致。

4. behavior.tests 覆盖验证（quality: production）：
   读 experiment/experiment.yaml 中已实现 behaviors（b-01~b-18, b-22~b-25，共 22 条）。
   跳过 b-19~b-21（system behaviors，Session 11 实现）。
   对每个已实现 behavior 的 tests 条目，确认有对应测试：
   - API behaviors → spec test assertion
   - UI behaviors → Playwright smoke/funnel assertion
   - Payment flows (b-22, b-23, b-25) → 深度 spec test（验证 handler 逻辑，不只是 auth guard）
   缺失的覆盖：补上。补完后重新运行 npm test 确认通过。

5. 生成 checkpoint report 写入 docs/cp3-report.md。

所有检查项通过后，报告结果。失败项必须修复后才能进入 Phase 5。
```

---

## Phase 5: Infrastructure

### Session 9a — Skill Execution API + Realtime (Vercel)

**目标**：实现 Vercel 侧的 skill execution API routes、Realtime 集成、approval gate pattern。

**输入**：Session 8 的 billing gate（skill execution 需要先 authorize）

**输出**：
- Skill execution API routes（execute, status, approve, cancel）
- `/api/operations/:id/extend` route
- Supabase Realtime streaming integration（browser 订阅）
- Approval gate pattern（Web UI 侧）

**输出合约**（Session 9b 验证）：
```
src/app/api/skills/execute/route.ts              → POST handler returning { execution_id }
src/app/api/skills/[id]/route.ts                 → GET handler
src/app/api/skills/[id]/approve/route.ts         → POST handler
src/app/api/skills/[id]/cancel/route.ts          → POST handler
src/app/api/operations/[id]/extend/route.ts      → POST handler
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/assayer-product-design.md Section 2（Skill Execution Model, Cloud Run Jobs, Agent SDK, Approval Gate Pattern）。
读 docs/CONVENTIONS.md。

注意：Agent SDK API shape（query, resumeSession, session.events）是 product-design.md 的示意代码。
实现前验证 @anthropic-ai/claude-agent-sdk 最新 API。如 API 不同，按实际实现，保持相同功能语义
（invoke skill → stream events → approval gate → resume）。

用 /change 实现 Vercel 侧 skill execution：

## 1. Skill Execution API Routes

POST /api/skills/execute:
a. Auth required
b. Billing gate: 调用 /api/operations/authorize（除非 free operation）
c. 创建 skill_executions row（status: pending）
d. 触发 Cloud Run Job — 提取为共享函数 `src/lib/cloud-run.ts` export `triggerCloudRunJob(params)`:
   - POST to Cloud Run Jobs API: /apis/run.googleapis.com/v2/.../jobs:run
   - Execution-specific env vars via overrides.containerOverrides[].env:
     EXPERIMENT_ID, SKILL_NAME, USER_ID, EXECUTION_ID,
     SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY,
     RAILWAY_TOKEN（用于 Railway hosting 的实验部署）
   - 此函数被两处调用：1) POST /api/skills/execute（用户触发），2) metrics-sync cron auto-fix（系统触发，Session 11）
e. 返回 { execution_id }

GET /api/skills/:id:
- Execution status + events

POST /api/skills/:id/approve:
- 更新 skill_executions status = 'running'（from 'paused'）
- Job 在 polling loop 中检测到变化，恢复执行

POST /api/skills/:id/cancel:
- 更新 status = 'failed'

## 2. Supabase Realtime Integration

Browser 订阅 Supabase Realtime channel `exec:{execution_id}`:

Channel authorization: `exec:{execution_id}` channels 需要验证 subscriber ownership。

**实现方案**：使用 Supabase Realtime **Broadcast** 模式（不是 Postgres Changes）。Broadcast channels 不经过 RLS — 它们是 ephemeral pub/sub。安全性通过以下方式保证：

1. **Channel name 不可猜测**: `exec:{execution_id}` 其中 execution_id 是 UUID — 知道 channel name 等价于拥有访问权
2. **执行 ID 只返回给 authenticated owner**: POST /api/skills/execute 在创建 skill_execution 后返回 execution_id，只有发起请求的 authenticated user 能拿到
3. **Frontend 在订阅前验证 auth**: Browser 端使用 authenticated Supabase client 订阅，确保只有登录用户能建立 Realtime 连接
4. **Server-side 使用 service role key 发布**: skill-runner.js 使用 SUPABASE_SERVICE_KEY 发布到 channel，不受 RLS 限制

```typescript
// Browser (authenticated user)
const supabase = createBrowserClient();
const channel = supabase.channel(`exec:${executionId}`);
channel.on('broadcast', { event: 'log' }, (payload) => { /* update UI */ });
channel.on('broadcast', { event: 'progress' }, (payload) => { /* update progress */ });
channel.on('broadcast', { event: 'gate' }, (payload) => { /* show approval UI */ });
channel.subscribe();

// skill-runner.js (service role)
const channel = supabase.channel(`exec:${executionId}`);
await channel.send({ type: 'broadcast', event: 'progress', payload: { pct: 50, phase: 'deploying' } });
```

Event types（来自 product-design.md）:
- log: { line: string, ts: number } — 输出流
- status: { status: "running" | "paused" | "completed" | "failed" } — 状态变更
- gate: { gate_type: string, prompt: string } — 触发 approval UI
- progress: { pct: number, phase: string, preview_url?: string } — 进度 + preview

前端 Launch page 已在 Session 6a 构建了 UI，本 session 连接真实的 Realtime events。

## 3. Approval Gate Pattern

实现 product-design.md 描述的 approval gate：
1. Job hits gate → writes status='paused' + gate_type to skill_executions
2. Job polls Supabase every 5s for status change
3. User approves via Web UI → POST /api/skills/:id/approve
4. Job detects change → resumes
5. 30min timeout → status='timed_out'

## 4. Token Budget Extension Route

POST /api/operations/:id/extend:
a. Auth required
b. 验证 original operation 属于当前用户且 skill_executions.status = 'paused' AND gate_type = 'budget_exceeded'
c. 计算 continuation 费用（same billing flow as /api/operations/authorize）
d. 创建新 operation_ledger row（parent_operation_id 指向原始 row）
e. 更新 skill_executions status → 'running'
f. 返回 { new_operation_id, charged_cents }

Environment variables 需要:
- GCP_PROJECT_ID, GCP_REGION
- CLOUD_RUN_JOB_NAME
- GCP_SA_KEY（Service Account for Vercel → Cloud Run invocation）

npm run build 零错误。
```

---

### Session 9b — Docker + skill-runner.js (Cloud Run)

**目标**：实现 Cloud Run Jobs 侧 — Docker image、skill-runner.js、workspace lifecycle、per-experiment hosting。

**输入**：Session 9a 的 Vercel 侧 API routes

**输出**：
- Docker image spec（`docker/Dockerfile`）
- `docker/skill-runner.js` entrypoint
- Token budget enforcement
- Per-experiment hosting setup（Vercel + Railway routing）
- Workspace lifecycle（8 steps）

**输出合约**（Session 10 验证）：
```
docker/Dockerfile       → exists with FROM node:20-slim base
docker/skill-runner.js  → exists, passes node --check
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/assayer-product-design.md Section 2（Cloud Run Jobs, Agent SDK, Workspace Lifecycle）。
读 docs/CONVENTIONS.md。

用 /change 实现 Cloud Run Jobs 侧：

## 1. Docker Image（Dockerfile）

创建 `docker/Dockerfile`（spec for Cloud Run Jobs container）:

| Layer | Contents |
|-------|----------|
| Base | node:20-slim |
| System deps | git, curl, jq |
| CLIs | vercel, @railway/cli, supabase, claude-code (Agent SDK) |
| Template | Pre-loaded mvp-template .claude/ directory |
| Entrypoint | skill-runner.js |

## 2. Skill Runner

创建 `docker/skill-runner.js`:
a. 读取 env vars（EXPERIMENT_ID, SKILL_NAME, etc.）
b. Clone experiment repo（existing）或 copy mvp-template（new）
c. Generate experiment.yaml from Supabase data
c2. Generate `.runs/spec-manifest.json` from Supabase experiment data（hypotheses, variants, metrics, round history）。/iterate skill 读取此 manifest 作为输入。
d. Inject env vars
e. 初始化 Supabase Realtime channel
f. Agent SDK runs skill
g. Stream events to Realtime channel
h. Approval gate handling（poll for resume）
i. Parse output → write to Supabase tables
j. Git push results

## 3. Token Budget Enforcement

k. Token budget enforcement:
   - 从 `operation_ledger` row 读取 `token_budget`（Session 8 创建的字段）
   - 通过 `ai_usage` rows（linked to this operation）追踪累积 input tokens
   - 每次 AI API call 前: check cumulative tokens vs budget
   - 80% budget: log warning to Realtime channel（`{ type: 'log', line: '⚠ Token budget 80% reached' }`）
   - 100% budget: gracefully stop skill，写 partial results to Supabase，发送 `{ type: 'gate', gate_type: 'budget_exceeded', used: N, budget: M, continue_cost_cents: X }` event on Realtime channel（复用 approval gate 事件模型，skill status 设为 `paused`）
   - Browser 显示 "Continue for $X?" modal（复用 approval gate UI pattern）
   - User approve → POST /api/operations/:id/extend → skill resume

## 4. Per-Experiment Hosting Setup

skill-runner.js 处理每个实验的 hosting 配置（/deploy skill 执行时）。根据 experiment.yaml `stack.hosting` 值路由：

### Vercel path（hosting: vercel — 默认）
- Vercel API 创建新 project（name = experiment slug）
- 配置 domain: {experiment-slug}.assayer.io
- 前提：assayer.io 域名配置 wildcard DNS（*.assayer.io → Vercel）
- 注入 experiment-specific env vars
- 部署: `vercel --prod`

### Railway path（hosting: railway — AI agent / long-running experiments）
- Railway CLI 创建新 project: `railway init` + `railway link`
- 配置 custom domain: `railway custom-domain add {experiment-slug}.assayer.io`
- 前提：assayer.io 域名 DNS 同时支持 Vercel（A record）和 Railway（CNAME per experiment）
- 注入 experiment-specific env vars: `railway variables set KEY=VALUE`（循环）
- 部署: `railway up --detach`
- Health check: `curl {experiment-slug}.assayer.io/api/health`
- 完整的 Railway Deploy Interface 参见 `.claude/stacks/hosting/railway.md`

### 路由逻辑（skill-runner.js 中实现）
```javascript
const hosting = experimentYaml.stack?.services?.[0]?.hosting || 'vercel';
if (hosting === 'railway') {
  await deployToRailway(experimentSlug, envVars);
} else {
  await deployToVercel(experimentSlug, envVars);
}
```

DNS 配置：
- Vercel experiments: wildcard DNS `*.assayer.io → Vercel`（A record 76.76.21.21）
- Railway experiments: per-experiment CNAME（`{slug}.assayer.io → {project}.up.railway.app`）
- 方案：Vercel wildcard 作为默认，Railway experiments 在部署时通过 Cloudflare API 添加 CNAME override

Cloudflare DNS API 集成（skill-runner.js 中实现）：
```javascript
// Only for Railway experiments — Vercel uses wildcard
async function addCloudflareCNAME(slug, railwayDomain) {
  const resp = await fetch(`https://api.cloudflare.com/client/v4/zones/${process.env.CLOUDFLARE_ZONE_ID}/dns_records`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${process.env.CLOUDFLARE_API_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ type: 'CNAME', name: `${slug}.assayer.io`, content: railwayDomain, proxied: true }),
  });
  if (!resp.ok) throw new Error(`Cloudflare DNS failed: ${await resp.text()}`);
}
```

Environment variables（添加到 S14 deploy checklist）:
- CLOUDFLARE_API_TOKEN（Zone:DNS:Edit permission）
- CLOUDFLARE_ZONE_ID（assayer.io zone ID）

## 5. Workspace Lifecycle

实现 product-design.md 的 8 步 lifecycle:
1. Container starts from Docker image
2. Clone or copy template
3. Generate experiment.yaml from Supabase
4. Inject env vars
5. Agent SDK runs skill
6. Git push results
7. Parse output → Supabase
   - **关键 status transition**: 当 skill_name = 'deploy' 且部署成功时：
     ```javascript
     // 7a. Update experiment status: draft → active
     await supabase.from('experiments')
       .update({ status: 'active', deployed_url: deployedUrl, started_at: new Date().toISOString() })
       .eq('id', experimentId);

     // 7b. Trigger experiment_live notification（立即发送，不等 daily cron）
     await supabase.from('notifications').insert({
       user_id: userId,
       experiment_id: experimentId,
       trigger_type: 'experiment_live',
       channel: 'email',
       scorecard_snapshot: null, // no metrics yet
       sent_at: new Date().toISOString(),
     });
     // Send email via Resend using experiment_live template（src/lib/email.ts）
     await sendNotificationEmail('experiment_live', { experimentName, deployedUrl, userEmail });
     ```
   - 这两步是 metrics-sync cron 和 notification 系统的前置条件：没有 `status = 'active'`，cron 不会处理此实验
8. Container destroyed

npm run build 零错误。
```

---

### Session 10 — Distribution System (6 Adapters)

**目标**：实现分发系统 — 6 个 adapter、channel setup、campaign management。

**输入**：Session 9 的 skill execution infrastructure

**输出**：
- Distribution adapter interface
- 6 adapters（twitter-organic, reddit-organic, email-resend, google-ads, meta-ads, twitter-ads）
- Distribution API routes
- Channel setup flow（OAuth）
- Campaign management（pause/resume/adjust）

**输出合约**（Session 11 验证）：
```
src/lib/distribution/types.ts                         → export interface DistributionAdapter { publish, measure, manage }
src/lib/distribution/adapters/twitter-organic.ts       → implements DistributionAdapter
src/lib/distribution/adapters/reddit-organic.ts        → implements DistributionAdapter
src/lib/distribution/adapters/email-resend.ts          → implements DistributionAdapter
src/lib/distribution/adapters/google-ads.ts            → implements DistributionAdapter
src/lib/distribution/adapters/meta-ads.ts              → implements DistributionAdapter
src/lib/distribution/adapters/twitter-ads.ts           → implements DistributionAdapter
src/app/api/experiments/[id]/distribution/route.ts     → GET handler
src/app/api/experiments/[id]/distribution/sync/route.ts    → POST handler
src/app/api/experiments/[id]/distribution/manage/route.ts  → POST handler
src/lib/distribution/plan-generator.ts                          → exports generateDistributionPlan(experiment, user) → DistributionPlan
src/app/api/experiments/[id]/distribution/plan/route.ts         → POST handler
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/assayer-product-design.md Section 2（Distribution Adapter Architecture）。

用 /change 实现分发系统：

## 1. Adapter Interface

创建 `src/lib/distribution/types.ts`:
```typescript
interface DistributionAdapter {
  publish(config: AdsYaml, credentials: OAuthTokens): Promise<{ campaign_id: string; campaign_url: string }>;
  measure(campaign_id: string, credentials: OAuthTokens): Promise<DistributionMetrics>;
  manage(campaign_id: string, action: 'pause' | 'resume' | 'update', credentials: OAuthTokens): Promise<void>;
}

interface DistributionMetrics {
  impressions: number;
  clicks: number;
  spend_cents: number;
  conversions: number;
  ctr: number;
  cpc_cents: number;
}
```

## 1b. 前置步骤：确认 meta-ads.md stack file

Session 0 已在 mvp-template 中创建 `.claude/stacks/distribution/meta-ads.md`。
验证该文件存在且包含 Meta Marketing API v21.0 的完整 spec（Ad Format, Targeting, API Procedure 等）。
如果 Session 0 尚未执行，需先在 mvp-template repo 中执行 Session 0。

## 2. Six Adapters

创建 `src/lib/distribution/adapters/`:

| Adapter | Tier | API |
|---------|------|-----|
| twitter-organic.ts | Free | X API v2 |
| reddit-organic.ts | Free | Reddit API |
| email-resend.ts | Free | Resend API |
| google-ads.ts | Paid | Google Ads API |
| meta-ads.ts | Paid | Meta Marketing API |
| twitter-ads.ts | Paid | X Ads API |

每个 adapter 实现 DistributionAdapter interface。

MCC / Partner billing model（paid ads）:
- Google Ads: MCC creates child customer account → user links payment method
- Meta Ads: Business Manager creates ad account
- Twitter Ads: user's own ads account → OAuth

Paid adapters 需要 Pro/Team plan（检查 user_billing.plan）。

## 3. Distribution API Routes

GET  /api/experiments/:id/distribution — list campaigns
POST /api/experiments/:id/distribution/sync — force metrics sync from ad platforms
POST /api/experiments/:id/distribution/manage — pause/resume/adjust:
  { campaign_id, action: 'pause' | 'resume' | 'update' }

## 4. Channel Setup（OAuth flows）

Settings 页面已在 Session 7 有 UI stub。
本 session 实现实际 OAuth 连接:

Organic:
- Twitter/X: OAuth 2.0 PKCE
- Reddit: OAuth 2.0
- Resend: API key（非 OAuth）

Paid:
- Google Ads: OAuth 2.0 + MCC sub-account creation
- Meta Ads: Facebook Login → Business Manager
- Twitter Ads: OAuth 1.0a

Token 存储: oauth_tokens 表（encrypted via Supabase Vault）。

**OAuth callback routes**（distribution channels 的 OAuth 回调，独立于 Supabase Auth 的 login OAuth）:

| Route | Provider | Flow |
|-------|----------|------|
| GET /api/distribution/callback/twitter | Twitter/X | OAuth 2.0 PKCE → exchange code → store tokens |
| GET /api/distribution/callback/reddit | Reddit | OAuth 2.0 → exchange code → store tokens |
| GET /api/distribution/callback/google-ads | Google Ads | OAuth 2.0 → exchange code + create MCC sub-account → store tokens |
| GET /api/distribution/callback/meta | Meta/Facebook | OAuth 2.0 → exchange code + get ad account → store tokens |
| GET /api/distribution/callback/twitter-ads | Twitter Ads | OAuth 1.0a → exchange request token → store tokens |

每个 callback route:
a. 验证 state parameter（防 CSRF）
b. Exchange authorization code for access + refresh tokens
c. Upsert oauth_tokens row（encrypted via Supabase Vault）
d. Redirect back to `/settings?channel=connected&provider={name}`

## 4b. OAuth Token Refresh & Expiration Handling

每个 distribution adapter 在调用 platform API 前必须检查 token 有效性：

```typescript
// src/lib/distribution/token-manager.ts
export async function getValidToken(userId: string, provider: string): Promise<string | null> {
  const token = await supabase.from('oauth_tokens')
    .select('access_token, refresh_token, expires_at')
    .eq('user_id', userId).eq('provider', provider).single();

  if (!token.data) return null;

  // Token still valid (5min buffer)
  if (new Date(token.data.expires_at) > new Date(Date.now() + 5 * 60 * 1000)) {
    return token.data.access_token;
  }

  // Token expired — attempt refresh
  try {
    const newTokens = await refreshOAuthToken(provider, token.data.refresh_token);
    await supabase.from('oauth_tokens')
      .update({ access_token: newTokens.access_token, expires_at: newTokens.expires_at })
      .eq('user_id', userId).eq('provider', provider);
    return newTokens.access_token;
  } catch (err) {
    // Refresh failed (token revoked by user on platform, or refresh token expired)
    // Create ad_account_suspended alert for this channel
    await supabase.from('experiment_alerts').insert({
      experiment_id: activeExperimentId,
      alert_type: 'ad_account_suspended',
      channel: provider,
      severity: 'warning',
      message: `${provider} connection expired. Please reconnect in Settings.`,
    });
    return null; // adapter.measure() will skip this channel
  }
}
```

关键点:
- adapter.measure() 调用 getValidToken() → null 时 skip 该 channel（不 crash，其他 channels 继续）
- adapter.publish() 调用 getValidToken() → null 时 return { status: 'failed', error: 'token_expired' }
- Settings Distribution Channels section: token 过期的 channel 显示 "Expired — [Reconnect]" 而非 "Connected"
- 检测逻辑：`oauth_tokens.expires_at < now()` OR adapter API 返回 401/403

将这些 routes 添加到输出合约中。

## 5. Plan-Gated Channels

distribution campaign 创建时检查用户 plan:
- Free/PAYG: only organic channels
- Pro/Team: all channels
- UI 中 paid channels 显示 "Pro plan required" badge

## 6. Mock→Real Wiring（连接前序 session 的 mock UI）

Session 6a（Launch page）和 Session 7（Settings page）构建了 distribution 相关 UI 但使用 mock 数据。本 session 必须将真实后端连接到这些 UI：

a. **Settings page Distribution Channels section**（S7 产物）:
   - 替换 mock OAuth 按钮为真实 OAuth redirect URLs（`/api/distribution/callback/{provider}`）
   - 连接 oauth_tokens 查询显示已连接状态（"@username connected [Disconnect]"）
   - [Disconnect] 按钮: DELETE oauth_tokens row for provider

b. **Launch page Phase E: Channel Setup**（S6a 产物）:
   - 替换 mock channel list 为真实 oauth_tokens 查询（已连接 vs 未连接）
   - [Connect Twitter →] 按钮: redirect to OAuth flow（same as Settings page）
   - 连接完成后 redirect 回 `/launch/[id]`（通过 callback URL query param）

c. **Launch page Phase F: Distribution Approval Gate**（S6a 产物）:
   - 替换 mock distribution plan 为 `POST /api/experiments/:id/distribution/plan` 调用
   - [Launch Distribution →] 按钮: 调用 `POST /api/skills/execute { skill: 'distribute' }`
   - [Edit Plan] 按钮: 修改 plan 参数后重新调用 plan generator

d. **Launch page Phase G: Distribution Live**（S6a 产物）:
   - 替换 mock channel status 为 `GET /api/experiments/:id/distribution` 查询

Environment variables:
- TWITTER_CLIENT_ID, TWITTER_CLIENT_SECRET
- REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET
- RESEND_API_KEY
- GOOGLE_ADS_MCC_ID, GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_DEVELOPER_TOKEN
- META_APP_ID, META_APP_SECRET
- TWITTER_ADS_CONSUMER_KEY, TWITTER_ADS_CONSUMER_SECRET

## Distribution Plan Generator

Read docs/assayer-product-design.md "Distribution Plan Generator" subsection.

### 1. Plan Generator Service

Create `src/lib/distribution/plan-generator.ts`:

export async function generateDistributionPlan(experiment, user): Promise<DistributionPlan>

Logic:
1. Determine budget range from experiment level:
   - L1 (Pitch): 5000-15000 cents ($50-150)
   - L2 (Prototype): 20000-50000 cents ($200-500)
   - L3 (Product): 50000-200000 cents ($500-2000)
   Use midpoint as default. Clamp to user's PAYG balance if insufficient.

2. Determine channel priority from experiment type + target_user:
   - B2B SaaS: google-ads 40%, email-resend 25%, twitter-organic 20%, reddit-organic 15%
   - Consumer App: meta-ads 35%, twitter-ads 20%, reddit-organic 25%, email-resend 20%
   - Developer Tool: reddit-organic 35%, twitter-organic 30%, google-ads 20%, email-resend 15%
   - Default: google-ads 40%, meta-ads 30%, twitter-ads 15%, organic 15%
   Infer type from experiment.yaml target_user keywords (e.g., "developer" → Developer Tool, "business" / "B2B" → B2B SaaS).

3. Filter by plan tier:
   - Free/PAYG: remove paid channels (google-ads, meta-ads, twitter-ads), redistribute budget to organic
   - Pro/Team: all channels available

4. Filter by connected channels:
   - Query oauth_tokens for user's connected channels
   - Unconnected channels: set available = false, include requires_connect message

5. Generate creative per available channel:
   - Read experiment name, description, thesis, variants
   - Read the landing page source to extract actual headline (message match)
   - For each channel: generate headlines + descriptions within channel format constraints
   - Use channel stack files (.claude/stacks/distribution/<channel>.md) for format limits

### 2. API Route

POST /api/experiments/:id/distribution/plan
  - Auth: required
  - Calls generateDistributionPlan(experiment, user)
  - Returns DistributionPlan (see product-design.md for interface)
  - Called by Session 6a Phase F UI when user reaches Distribution Approval Gate

### 3. Phase-Gated Budget Progression

When returning plan for an experiment that has completed a previous /iterate cycle:
  - Read the latest verdict from experiment_decisions
  - If verdict = SCALE and previous budget was Phase 1 range → suggest Phase 2 budget
  - If verdict = REFINE → maintain budget, optimize channel mix based on best_channel from metrics
  - If verdict = KILL/PIVOT → suggest $0 (stop spend)
  - Include reasoning in DistributionPlan.reasoning field

npm run build 零错误。
```

---

### [CP4] Checkpoint: Infrastructure

**验证范围**：Sessions 9a-10 的所有输出。

**检查项**：
1. `npm run build` 零错误
2. `npx tsc --noEmit` 零错误
3. `npm test` 通过
4. Skill execution API routes 返回正确 HTTP status：
   - `POST /api/skills/execute` → 200 with { execution_id }（需 auth + billing gate）
   - `GET /api/skills/:id` → 200 with execution status
   - `POST /api/skills/:id/approve` → 200
5. `docker/Dockerfile` 存在且语法正确（`docker build --check` or similar）
6. `docker/skill-runner.js` 存在且 `node --check docker/skill-runner.js` 通过
7. Distribution adapter interface types 正确
8. 6 adapters 实现 DistributionAdapter interface
9. OAuth flow routes 存在
10. Realtime channel 订阅模式正确
11. `quality: production` — 已实现 behaviors (b-01~b-18, b-22~b-29) 的 `tests` 条目均有对应 spec test 或 Playwright assertion。注意：b-19~b-21（system behaviors）在 Session 11 实现，CP4 跳过验证，CP5 要求 100% 覆盖。

**输出**：CP4 verification report。失败项必须修复后才能进入 Phase 6。

**Prompt**:

```
执行 [CP4] Checkpoint: Infrastructure。

验证范围：Sessions 9a-10 的所有输出。

步骤：

1. 运行自动化检查：
   - `npm run build`（零错误）
   - `npx tsc --noEmit`（零错误）
   - `npm test`（全部通过）
   如有失败，修复后重新运行，最多 3 次。

2. Infrastructure 验证：
   - 确认 Skill execution API routes 返回正确 HTTP status
   - 确认 Docker 配置存在且语法正确
   - 确认 Distribution adapter interface + 6 adapters
   - 确认 OAuth flow routes 存在
   - 确认 Realtime channel 订阅模式正确

3. behavior.tests 覆盖验证（quality: production）：
   读 experiment/experiment.yaml 中已实现 behaviors（b-01~b-18, b-22~b-29，共 25 条）。
   跳过 b-19~b-21（system behaviors，Session 11 实现）。
   对每个已实现 behavior 的 tests 条目，确认有对应测试。
   缺失的覆盖：补上。补完后重新运行 npm test 确认通过。

4. 生成 checkpoint report 写入 docs/cp4-report.md。

所有检查项通过后，报告结果。失败项必须修复后才能进入 Phase 6。
```

---

## Phase 6: Automation

### Session 11 — Metrics Cron + Alerts + Verdict Engine + Notifications

**目标**：实现自动化后台 — 15 分钟 metrics sync、alert 检测、verdict engine、notification dispatch。

**输入**：Session 10 的 distribution + Session 6 的 experiment page（scorecard + alerts）

**输出**：
- Metrics sync cron（15 min）
- Alert detection + experiment_alerts
- Verdict engine（decision framework）
- Notification dispatch（7 triggers）
- Email templates（Resend）
- Anonymous spec cleanup cron（1h）

**输出合约**（Session 12a 验证）：
```
src/app/api/cron/metrics-sync/route.ts     → GET handler with CRON_SECRET verification
src/app/api/cron/cleanup/route.ts          → GET handler
src/app/api/cron/notifications/route.ts    → GET handler
src/app/api/cron/cost-monitor/route.ts     → GET handler
src/app/api/experiments/[id]/alerts/route.ts → GET handler
src/app/api/notifications/route.ts          → GET handler
src/lib/email.ts                            → email template functions
vercel.json                                 → contains "crons" configuration
src/app/api/cron/compute-scores/route.ts    → POST handler (cron)
src/app/api/cron/generate-insights/route.ts → POST handler (cron)
src/app/api/cron/auto-rebalance/route.ts    → POST handler (cron)
src/lib/assayer-score.ts                    → exports computeAssayerScore(experiment) → number
src/lib/portfolio-insight.ts                → exports generatePortfolioInsight(userId) → PortfolioInsight
src/lib/thompson-sampling.ts                → exports computeAllocation(experiments) → BudgetAllocation
Email template: portfolio-update            → (in notification templates)
Distribution ROI computation                → integrated into verdict generation
experiment_decisions.distribution_roi       → jsonb field populated on verdict
Confidence bands                            → stored in experiment_metric_snapshots per dimension
public/sw.js                               → Service Worker for browser push notifications
src/lib/push-notifications.ts              → exports requestPushPermission(), sendPushSubscriptionToServer()
```

**Prompt 1 of 3 — Metrics Sync + Alert Detection**（新对话）:

```
读 docs/assayer-session-prompts.md Session 11 的「输入合约验证」和前序 session 的「输出合约」，执行 preamble 验证。
读 docs/assayer-product-design.md Section 3（Flow 4: Metrics Sync）、Section 8（Alert System）。
读 docs/CONVENTIONS.md。

### 现状（bootstrap + CP1 产物，需大幅增强）

已有 cron routes（全部是 stub，验证 CRON_SECRET 后返回 mock 响应）:
- `src/app/api/cron/metrics-sync/route.ts`：query running experiments + update synced_at timestamp（不调用 PostHog 或 ad platform API）
- `src/app/api/cron/alert-detection/route.ts`：检查 budget exhaustion + stale metrics + dimension dropping（CP1 新增）。使用 `distributions` 表名（migration 002 实际表名是 `distribution_campaigns`，需要修正）。budget exhaustion 检查使用 `.eq("resolved", false)`（migration 002 的列是 `resolved_at timestamptz`，需要修正为 `.is("resolved_at", null)`）
- `src/app/api/cron/spec-cleanup/route.ts`：删除 anonymous specs（使用 `specs` 表，migration 002 实际表名是 `anonymous_specs`，需要修正）

缺少: PostHog Events API 集成、ad platform adapter 集成、scorecard ratio 计算、force sync endpoint、per-hypothesis verdict integration。

### 改动要点

1. **增强 metrics-sync**：接入 PostHog Events API + ad platform adapters（paid channels）+ UTM-based tracking（organic channels）
2. **修正 alert-detection**：表名 `distributions` → `distribution_campaigns`，`resolved` → `resolved_at`
3. **修正 spec-cleanup**：表名 `specs` → `anonymous_specs`，`user_id IS NULL` → `expires_at < now()`
4. **新增** scorecard ratio 计算 + experiment_metric_snapshots 写入
5. **新增** force sync endpoint（POST /api/experiments/:id/metrics/sync）with "Analyze Now" guard clause
6. **新增** runtime auto-fix detection（L2/L3）

这是 Session 11 /change 1 of 3。用 /change 实现 metrics sync + alert detection：

## 1. Metrics Sync Cron（每 15 分钟）

创建 Vercel Cron `/api/cron/metrics-sync`:

a. Query all experiments WHERE status IN ('active', 'verdict_ready')
b. For each experiment, 分两步收集 metrics:

   **Step 1: Paid channel metrics（API 直接获取）**
   - 对 distribution_campaigns WHERE status = 'active' AND channel IN ('google-ads', 'meta-ads', 'twitter-ads')
   - 调用对应 adapter.measure() → impressions, clicks, spend, CTR, CPC
   - 更新 distribution_campaigns 行

   **Step 2: All channel metrics via PostHog（UTM 追踪）**
   - PostHog Events API 查询该 experiment 的 landing page 事件（按 utm_source 分组）
   - **Organic channels（twitter-organic, reddit-organic, email-resend）没有平台 API metrics。**
     它们的 clicks 只能通过 PostHog 的 UTM params 间接追踪:
     `utm_source=twitter&utm_medium=organic`, `utm_source=reddit&utm_medium=organic`, `utm_source=email&utm_medium=campaign`
   - PostHog API 也提供 behavior metrics（signups via `signup_complete` event, CTA clicks via `cta_click` event）

   **Merge 策略**: Paid channels 使用 ad platform API 的 impressions/spend 数据 + PostHog 的 conversion 数据。
   Organic channels 仅使用 PostHog UTM-filtered 数据（clicks = page views with matching utm_source）。

c. 写入 experiment_metric_snapshots（time-series），channel_metrics jsonb 包含 per-channel breakdown
d. 计算 scorecard ratios:
   - REACH  = actual_CTR / threshold_CTR → ratio（paid channels 用 ad platform CTR；organic 用 PostHog clicks / total reach 估算）
   - DEMAND = actual_signup_rate / threshold → ratio（PostHog signup_complete event / total visitors）
   - ACTIVATE = actual_activation_rate / threshold → ratio（PostHog activate event / total signups, L2+ only）
   - MONETIZE = actual_pricing_clicks / threshold → ratio（PostHog cta_click on pricing / total visitors）
   - RETAIN = actual_return_rate / threshold → ratio（PostHog returning visitors / total visitors, L3 only）
e. Confidence bands: <30 insufficient, 30-100 directional, 100-500 reliable, 500+ high

Force sync route: POST /api/experiments/:id/metrics/sync?force_verdict=true
- 不带 force_verdict: 仅 sync metrics（default）
- 带 force_verdict=true: sync + 运行 verdict engine（"Analyze Now" 按钮使用）
- **Analyze Now 的 guard clause 由后端判断**（不依赖前端）:
  后端检查 total_clicks < 100 OR experiment duration < 50% estimated_days
  如果 guard 触发: 返回 `{ verdict: null, guard: { clicks: 52, needed: 100, days_pct: 29, directional_signal: {...} } }`
  前端收到 guard 响应后显示 inline dialog（Session 6b 的 "Not Enough Data Yet" UI）
  如果 guard 通过: 返回 `{ verdict: 'scale'|'refine'|'pivot'|'kill', ... }`，前端重定向到 /verdict/[id]

GET /api/experiments/:id/metrics — cached scorecard（最新 metric_snapshot row）

## 1b. Mock→Real Wiring（连接前序 session 的 mock UI）

Session 6b（Experiment page）构建了 scorecard、traffic、live assessment 和 alert banners，但使用 mock 数据。本 session 必须将真实后端连接到这些 UI：

a. **Experiment page Scorecard**（S6b 产物）:
   - 替换 mock scorecard data 为 `GET /api/experiments/:id/metrics` 调用
   - 5-dimension progress bars 读取 experiment_metric_snapshots 的 reach/demand/activate/monetize/retain ratios
   - Confidence bands 从 metrics response 的 event_count 字段计算

b. **Experiment page Traffic section**（S6b 产物）:
   - 替换 mock per-channel data 为 metrics response 的 channel_metrics jsonb
   - Budget progress bar: distribution_campaigns 的 SUM(spend_cents) / experiment.budget

c. **Experiment page Live Assessment**（S6b 产物）:
   - 替换 mock bottleneck/projected verdict 为 metrics response 的 computed values
   - [Analyze Now] 按钮连接到 `POST /api/experiments/:id/metrics/sync?force_verdict=true`

d. **Experiment page Alert Banners**（S6b 产物）:
   - 替换 mock alerts 为 `GET /api/experiments/:id/alerts` 调用
   - Alert action buttons: [Force Sync] → POST metrics/sync, [Add Budget] → navigate to billing

e. **Lab page cards**（S7 产物）:
   - 替换 mock scorecard ratios 为 experiments.assayer_score（computed by metrics cron）
   - Pull-to-refresh: POST /api/experiments/:id/metrics/sync for each running experiment

## 2. Alert Detection

在 metrics sync 中检测 alert conditions:

| Condition | Alert Type |
|-----------|-----------|
| spend / budget > 0.9 | budget_exhausted |
| dimension ratio declining > 10% | dimension_dropping |
| last_sync > 26h | metrics_stale |
| ad account suspended | ad_account_suspended |
| DEMAND ratio = 0.0x with 50+ clicks | runtime bug（auto-fix trigger）|
| ACTIVATE ratio = 0.0x with 20+ signups | runtime bug（auto-fix trigger）|
| MONETIZE ratio = 0.0x with 30+ signups | runtime bug（auto-fix trigger）|
| Any page returning 5xx errors in PostHog data | runtime bug（auto-fix trigger）|

创建 experiment_alerts rows（severity: info/warning/critical）。

post_removed alert（Reddit/Twitter organic）:
- 检测: distribution adapter measure() 返回 404 或 post_status=removed
- Alert action button: [Repost to different subreddit] → 触发 distribution adapter publish() with 新 subreddit config（用户选择或 AI 推荐替代 subreddit）
- Alert type: post_removed, severity: warning

Alert API:
- GET  /api/experiments/:id/alerts — list unresolved
- PATCH /api/experiments/:id/alerts/:alertId — resolve/dismiss

Runtime auto-fix detection（L2/L3）:
- 0.0x ratio with sufficient traffic → trigger auto-fix chain
- Auto-fix 操作对用户始终免费

**Auto-fix triggering机制（cron → Cloud Run 的完整链路）**：

```
metrics-sync cron 检测到异常（0.0x ratio + sufficient traffic）
  │
  ├── 1. 创建 operation_ledger row:
  │      operation_type = 'auto_fix'
  │      billing_source = 'free'
  │      price_cents = 0
  │      token_budget = 1_500_000 (same as small_fix)
  │      status = 'authorized'
  │
  ├── 2. 创建 skill_executions row:
  │      skill_name = 'verify'
  │      status = 'pending'
  │      input_params = { experiment_id, auto_fix: true, anomaly_type, anomaly_dimension }
  │
  ├── 3. 内部调用 Cloud Run Job trigger（与 POST /api/skills/execute 相同逻辑）:
  │      使用 SUPABASE_SERVICE_ROLE_KEY（非用户 JWT）
  │      Cloud Run Job 执行: /verify → 如果发现 bug → /change → redeploy
  │
  ├── 4. skill-runner.js 完成后:
  │      更新 skill_executions status = 'completed'
  │      更新 operation_ledger actual_tokens_used + status = 'completed'
  │      （billing_source='free' → 不扣费）
  │
  └── 5. 创建 bug_auto_fixed alert + notification（即时发送，不等 daily cron）
```

关键实现点：
- 复用 Session 9a 的 `triggerCloudRunJob()` 函数（从 `/api/skills/execute` route 中提取为 `src/lib/cloud-run.ts` 共享函数）
- Auto-fix 的 operation_ledger 用 billing_source='free'，POST /api/operations/complete 检测到 free → 跳过扣费

**Runtime auto-fix retry 逻辑（区别于 Quality Gate auto-fix）**：

| 维度 | Quality Gate auto-fix（Session 6a Phase B） | Runtime auto-fix（Session 11 cron） |
|------|---------------------------------------------|--------------------------------------|
| 触发 | /deploy 过程中 behavior test 失败 | 15min metrics cron 检测到 0.0x ratio |
| 重试 | 3 次 retry，用户在 Launch page 实时看到进度 | 3 次 retry，每次间隔 15 min（cron 自然间隔） |
| 失败后 | 用户选择 [Simplify] / [Skip] / [Describe fix] | 创建 dimension_dropping alert，用户在 Experiment page 看到 |
| 用户参与 | 实时（Launch page 交互） | 异步（alert + email 通知） |
| Token budget | 使用 create 操作的剩余 budget | 独立 operation_ledger（1.5M per attempt） |

Runtime auto-fix retry 规则：
- **什么算 1 次 retry**: 1 次 `triggerCloudRunJob(verify)` 调用 = 1 次 retry。每次 retry 创建独立的 operation_ledger + skill_executions 行
- **重试间隔**: 不主动 sleep — 依赖 15 min cron 间隔作为自然 backoff。如果 cron 再次检测到同一 experiment 的 0.0x ratio 且 skill_executions 中有前次 auto_fix 记录（status='failed'），则 increment retry_count
- **重试上限**: 同一 experiment + 同一 anomaly_dimension，max 3 次 auto-fix attempts。检查: `SELECT count(*) FROM skill_executions WHERE experiment_id = ? AND input_params->>'auto_fix' = 'true' AND input_params->>'anomaly_dimension' = ? AND created_at > now() - interval '7 days'`
- **3 次失败后**: 创建 dimension_dropping alert（severity: warning），通知用户手动处理。不再自动触发 auto-fix for 该 dimension，直到用户手动发起 /change 或 dismiss alert
- **成功后**: 创建 bug_auto_fixed alert + immediate notification，reset retry counter（delete 或 ignore 之前的 failed skill_executions）

## 2b. /iterate Skill Integration

Metrics sync cron 调用 /iterate skill 逻辑（而非仅 inline decision framework）:
- 读取 spec-manifest.json（由 skill-runner.js 在 Session 9 生成）
- 运行 per-hypothesis verdict: 每个 hypothesis 独立判定 CONFIRMED / REJECTED / INCONCLUSIVE
- 写入 hypotheses 表 status 字段（passed = CONFIRMED, failed = REJECTED, testing = INCONCLUSIVE）
- 生成 iterate-manifest.json: { experiment_id, round, verdict, bottleneck, recommendations, variant_winner, analyzed_at, hypothesis_verdicts, funnel_scores }
- Experiment-level verdict 由 per-hypothesis verdicts 聚合得出（all CONFIRMED → SCALE, any top-funnel REJECTED → KILL, etc.）

npm run build 零错误。
```

**Prompt 2 of 3 — Verdict Engine + /iterate Integration**（新对话）:

```
读 docs/assayer-session-prompts.md Session 11。
读 docs/assayer-product-design.md Section 3（decision framework）。
读 docs/CONVENTIONS.md。

前置验证：确认 /change 1 已完成 —
- metrics-sync route 集成 PostHog Events API
- alert-detection route 使用正确表名（distribution_campaigns, resolved_at）
- force sync endpoint 存在（POST /api/experiments/:id/metrics/sync）

### 现状（/change 1 已完成 metrics sync）

Metrics sync 和 alert detection 已增强。但 verdict engine（decision framework）和 /iterate per-hypothesis verdict 尚未实现。
`experiment_decisions` 表存在（migration 002）但无 `variant_winner` 列。

### 改动要点

1. **新增** verdict engine with decision framework（SCALE/KILL/PIVOT/REFINE rules）
2. **新增** /iterate skill integration（per-hypothesis verdict: CONFIRMED/REJECTED/INCONCLUSIVE）
3. **新增** `variant_winner` 列（ALTER TABLE migration）
4. **新增** "Analyze Now" guard clause（total_clicks < 100 OR duration < 50%）— 后端判断
5. **集成到** force sync endpoint（force_verdict=true 触发 verdict engine）

这是 Session 11 /change 2 of 3。用 /change 实现 verdict engine。

Verdict Engine — Decision framework:
| Condition | Decision |
|-----------|----------|
| All tested dimensions >= 1.0 | SCALE |
| Any top-funnel (REACH or DEMAND) < 0.5 | KILL |
| 2+ dimensions < 0.8 | PIVOT |
| 1+ dimensions < 1.0 but fewer than 2 below 0.8 | REFINE |

Guard clause: Total clicks < 100 OR experiment duration < 50% of estimated_days → return null (no verdict).
Two-tier: guard clause first, then per-dimension ratio analysis.
Dependency-aware: parent hypothesis REJECTED → dependent hypotheses BLOCKED.

Verdict 产生后: write experiment_decisions row (decision, ratios, confidence, bottleneck, reasoning, distribution_roi, variant_winner), update experiment status → verdict_ready, trigger verdict_ready notification.

npm run build 零错误。
```

**Prompt 3 of 3 — Notifications + Cleanup + Cron Config**（新对话）:

```
读 docs/assayer-session-prompts.md Session 11。
读 docs/assayer-product-design.md Section 7（Notification System）。
读 docs/ux-design.md Notifications & Re-engagement section。
读 docs/CONVENTIONS.md。

前置验证：确认 /change 1-2 已完成 —
- metrics-sync 集成 PostHog
- verdict engine 存在（experiment_decisions 写入 + status → verdict_ready）
- alert detection 使用正确表名

### 现状（bootstrap stub + /change 1-2 已完成 metrics + verdict）

`src/app/api/cron/notifications/route.ts`：基础 stub，query verdict_ready experiments + critical alerts → 创建 notification rows。不发送 email，没有 7 种 trigger 模板，没有 Resend API 集成。
`src/app/api/cron/spec-cleanup/route.ts`：已由 /change 1 修正表名。
缺少: email templates（Resend）、7 种 notification triggers、notification CRUD API、cost-monitor cron、vercel.json crons config。

### 改动要点

1. **增强 notifications cron**：7 种 trigger templates + Resend API 集成
2. **新建** `src/lib/email.ts`：email template functions with mini scorecard
3. **新建** notification CRUD routes（GET /api/notifications, PATCH, POST mark-all-read）
4. **新建** `/api/cron/cost-monitor`：weekly internal margin monitoring
5. **新建/更新** `vercel.json`：crons configuration for all cron routes

这是 Session 11 /change 3 of 3。用 /change 实现 notifications + cleanup + cron config。

注意：Verdict Engine（## 3）已在 /change 2 中实现。本 /change 从 ## 4 开始。

Verdict 产生后:
a. Write experiment_decisions row，包含:
   - decision, all dimension ratios + confidence + sample_size
   - bottleneck_dimension, bottleneck_recommendation
   - reasoning (AI-generated analysis text)
   - next_steps (recommendations for REFINE/PIVOT)
   - **distribution_roi** (jsonb): 聚合 distribution_campaigns 数据，包含:
     ```json
     {
       "total_spend_cents": 20000,
       "total_clicks": 502,
       "avg_cpc_cents": 40,
       "per_channel": [
         { "channel": "google-ads", "spend_cents": 5200, "clicks": 312, "ctr": 3.8, "cpc_cents": 17 },
         { "channel": "twitter-organic", "spend_cents": 0, "clicks": 112, "ctr": null, "cpc_cents": 0 },
         ...
       ],
       "best_channel": "google-ads",
       "worst_channel": "meta-ads",
       "recommendations": ["Double Google Ads budget", "Cut Meta Ads"]
     }
     ```
     数据来源: SELECT FROM distribution_campaigns WHERE experiment_id = :id AND round_number = current_round
   - **variant_winner** (text): 需要在 experiment_decisions 表新增 `variant_winner text` 列（通过 migration: `ALTER TABLE experiment_decisions ADD COLUMN variant_winner text;`）。从 PostHog variant A/B 数据中确定表现最佳的 variant slug，写入此列。如果 confidence 不足则为 null。
b. Update experiment status → verdict_ready
c. Trigger verdict_ready notification

Also handle "Analyze Now" button: POST /api/experiments/:id/metrics/sync with force_verdict=true。

## 4. Notification Dispatch

7 种 notification triggers（product-design.md Section 7）:

| # | Trigger | Timing |
|---|---------|--------|
| 1 | experiment_live | Immediate after deploy |
| 2 | first_traffic | ~24h（检测: total_clicks 首次 > 10）|
| 3 | mid_experiment | ~Day 3（检测: estimated_days * 0.4）|
| 4 | verdict_ready | When verdict produced |
| 5 | budget_alert | When spend/budget > 0.9 |
| 6 | dimension_dropping | When decline detected |
| 7 | bug_auto_fixed | After auto-fix completes |

实现:
- 创建 notifications row
- 使用 Resend API 发送 email
- Email 模板包含 mini scorecard（ux-design.md 明确要求: "enough info to decide without opening app"）
- 使用 inline HTML 构建邮件模板（参照 .claude/stacks/email/resend.md 模式）
- 每种 trigger 一个模板函数（src/lib/email.ts），包含 experiment name + scorecard bars + CTA button
- Daily cron 检测 triggers 2, 3, 5, 6

### /api/cron/notifications route handler

创建 `src/app/api/cron/notifications/route.ts`:
a. 验证 CRON_SECRET（Vercel Cron 安全机制）
b. Query experiments WHERE status = 'active'
c. 对每个 experiment 检测 4 种 daily triggers:
   - Trigger 2 (first_traffic): total_clicks 首次 > 10 且未发送过此 notification
   - Trigger 3 (mid_experiment): 当前天数 >= estimated_days * 0.4 且未发送过
   - Trigger 5 (budget_alert): spend/budget > 0.9 且未发送过
   - Trigger 6 (dimension_dropping): 任一 dimension ratio 较前次下降 > 10% 且未发送过
d. 对每个触发的 notification: 创建 notifications row + 使用对应模板函数生成 email HTML + Resend API 发送
e. 返回 { processed: number, notifications_sent: number }

注意: Triggers 1 (experiment_live) 和 4 (verdict_ready) 是即时触发（在部署完成和 verdict engine 中直接发送），不经过 cron。
Trigger 7 (bug_auto_fixed) 是即时触发（在 auto-fix 完成时直接发送），不经过 daily cron。将 bug_auto_fixed 加入 daily cron 的检测列表作为 fallback（检测: auto-fix 完成但 notification 未发送的情况）。

## 4b. Internal Cost Monitoring Cron（weekly）

创建 Vercel Cron `/api/cron/cost-monitor`（weekly, Sunday 00:00 UTC）:
- 计算 blended margin: (total_charged - total_actual_cost) / total_charged across all operations this week
- 检查 hard limit hit rate: count(operations WHERE actual_tokens_used > token_budget) / total_operations
- 检查 auto-fix rate: count(bug_auto_fixed alerts) / total_active_experiments
- **Cloud Run budget monitoring**（product-design.md §10 约束）:
  - Query Cloud Run billing API (或 GCP Budget API) 获取当月 Cloud Run compute 花费
  - $50/mo alert: 当月花费 >= $50 → PostHog event `cloud_run_budget_alert` + 发送内部 alert email
  - $100/mo hard limit: 当月花费 >= $100 → 设置 feature flag 暂停新 Cloud Run Job 调度，PostHog event `cloud_run_budget_hard_limit` + 紧急 alert email
  - 在 `/api/operations/authorize` billing gate 中增加 Cloud Run hard limit 检查：如果 hard limit 已触发，拒绝需要 Cloud Run 的操作（返回 503 + 用户友好提示）
- PostHog server events: platform_margin_weekly { blended_margin_pct, hard_limit_hit_rate, auto_fix_rate, total_revenue_cents, total_cost_cents, cloud_run_spend_cents }
- 用于内部 PostHog monitoring dashboard（不面向用户）

## 5. Anonymous Spec Cleanup Cron（每 1 小时）

Vercel Cron `/api/cron/cleanup`:
- DELETE FROM anonymous_specs WHERE expires_at < now()

## 5b. Notification CRUD Routes

GET /api/notifications:
- Auth required，paginated（newest first），包含 unread_count
- Filter: ?unread=true

PATCH /api/notifications/:id:
- Auth required，更新状态: { read: true } 或 { dismissed: true }
- 验证通知属于当前用户

POST /api/notifications/mark-all-read:
- Auth required，批量标记所有未读为已读

注意：这些 notification CRUD routes 仅用于后端 dispatch + email delivery 追踪。
MVP 不构建 in-app notification center UI（per ux-design.md: "No in-app notification center"）。

## 5c. Browser Push Notifications（opt-in）

ux-design.md 明确要求 "Email (required) + browser push (opt-in)"。实现 Web Push API：

1. 创建 `public/sw.js`（Service Worker）:
   - 监听 `push` event → 显示 notification（title, body, icon, click → open experiment page）
   - 监听 `notificationclick` event → `clients.openWindow(data.url)`

2. 创建 `src/lib/push-notifications.ts`:
   - `requestPushPermission()`: 请求 Notification permission → 注册 Service Worker → `pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: NEXT_PUBLIC_VAPID_PUBLIC_KEY })`
   - `sendPushSubscriptionToServer(subscription)`: POST /api/notifications/push-subscribe → 存储 subscription endpoint + keys 到 notifications 表新增的 `push_subscription jsonb` 字段（或独立 `push_subscriptions` 表）

3. Settings 页面集成:
   - NOTIFICATIONS section（Account tab 内）: "Browser notifications" toggle
   - Toggle ON → 调用 `requestPushPermission()` → 存储 subscription
   - Toggle OFF → `pushManager.getSubscription().then(s => s.unsubscribe())` → 删除服务端 subscription

4. 发送 push:
   - 在现有 email dispatch 逻辑旁添加 push dispatch
   - 使用 `web-push` npm 包（`npm install web-push`）
   - 每个 notification trigger（7 种）同时发送 email + push（如果用户已订阅）
   - Push payload: `{ title: "Assayer", body: "<trigger-specific message>", data: { url: "/experiment/{id}" } }`

5. Environment variables（添加到 .env.example）:
   - `NEXT_PUBLIC_VAPID_PUBLIC_KEY` — VAPID public key（`web-push generate-vapid-keys`）
   - `VAPID_PRIVATE_KEY` — VAPID private key
   - `VAPID_SUBJECT` — mailto:support@assayer.io

6. DB migration: `ALTER TABLE notifications ADD COLUMN push_sent_at timestamptz;`
   或创建独立 `push_subscriptions` 表（user_id, endpoint, p256dh, auth, created_at）。
   选择独立表更清晰 — 一个用户可能有多个设备。

## 6. Vercel Cron Configuration

vercel.json crons:
- /api/cron/metrics-sync: every 15 minutes（scorecard + alerts + verdict engine）
- /api/cron/cleanup: every hour（anonymous_specs TTL）
- /api/cron/notifications: daily at 9am UTC（检测 triggers 2, 3, 5, 6 — first_traffic, mid_experiment, budget_alert, dimension_dropping）
- /api/cron/cost-monitor: weekly, Sunday 00:00 UTC（internal margin + hit rate + auto-fix rate monitoring）
- /api/cron/hosting-billing: monthly, 1st of month 00:00 UTC（hosting fee billing for active experiments, Session 8 §7）
- /api/cron/compute-scores: every 15 minutes（同 metrics-sync 频率，Portfolio Intelligence Score 计算）
- /api/cron/generate-insights: daily at 06:00 UTC（AI Portfolio Insight 生成）
- /api/cron/auto-rebalance: daily at 07:00 UTC（Team plan auto budget rebalance）

注意: Vercel Cron 需要 CRON_SECRET 环境变量验证。

## Portfolio Intelligence Crons

### 1. Assayer Score Computation (runs with existing 15-minute metrics cron)

After syncing PostHog metrics for each experiment, compute Assayer Score:
- Read latest experiment_metric_snapshots for reach, demand, monetize, retain dimensions
- Apply formula from product-design.md "Assayer Score (Portfolio Ranking)" section
- Write score to experiments.assayer_score and experiments.score_updated_at
- Skip experiments with no metric data (leave score as NULL)

### 2. AI Insight Generation (new daily cron)

New cron job (daily, 06:00 UTC):
- For each user with 2+ RUNNING experiments:
  - Collect: experiment name, assayer_score, funnel_scores, budget_spent, activations, best_channel, days_elapsed, days_total for each RUNNING experiment
  - Call Anthropic API (claude-sonnet-4-6) with structured output schema (PortfolioInsight)
  - Write result to portfolio_insights table
  - If previous non-dismissed insight exists, auto-dismiss it (replaced by new)
- Cost per user: ~$0.05 (Sonnet, ~2K input + 500 output tokens)

### 3. Auto-Rebalance (new daily cron, Team plan only)

New cron job (daily, after insight generation, 07:00 UTC):
- For Team plan users with auto-rebalance enabled (setting in user preferences):
  - Read latest portfolio_insight
  - If insight contains type='rebalance' recommendations:
    - Apply Thompson Sampling: sample from Beta(1+activations, 1+signups-activations) per experiment
    - Normalize to percentages, compute recommended allocation
    - Compare with current allocation — if drift > 10%, write new budget_allocation and apply
    - Log the rebalance to budget_allocations table with source='auto_rebalance'
- For users without auto-rebalance enabled: insight is written as recommendation only (applied manually via UI)

### 4. Portfolio Notification (extend existing notification dispatch)

Add to the daily notification dispatch:
- When a new portfolio_insight is generated for a user:
  - Send Portfolio Update email with:
    - ★ Portfolio Health score
    - Per-experiment row: name, score, trend (compare with previous day's score), status
    - Top suggested action
    - [Open Lab ->] deep link
  - Use the email template from ux-design.md Notifications section

## Distribution ROI Computation

Add to the verdict generation logic (after computing per-dimension ratios):

When generating a verdict for an experiment:
1. Query distribution_campaigns for the experiment: SUM(spend_cents), per-channel breakdown
2. Query PostHog activate event count for the experiment
3. Compute:
   - total_spend_cents = SUM(distribution_campaigns.spend_cents)
   - total_activations = COUNT(activate events)
   - cpa_cents = total_spend_cents / max(total_activations, 1)
   - signal_ratio = weighted average of dimension ratios (same weights as Assayer Score)
   - best_channel = channel with lowest CPA (most activations per dollar)
4. Write to experiment_decisions.distribution_roi (jsonb):
   { total_spend_cents, total_activations, cpa_cents, signal_ratio,
     display: "$X spent → Y.Zx signal", best_channel, channel_breakdown[] }
5. Session 7 verdict page reads this field and displays:
   - ROI summary line: "$47 spent → 3.2x signal"
   - Channel breakdown table: Channel | Spend | Activations | CPA
   - Best channel highlight

## Confidence Bands — Explicit Computation

Expand the existing scorecard ratio computation with explicit confidence band logic:

After computing each dimension's ratio, also compute its confidence level:

1. Count total events relevant to the dimension:
   - REACH: total ad impressions + organic visits
   - DEMAND: total landing page visits
   - ACTIVATE: total signups (only if L2+)
   - MONETIZE: total CTA clicks (only if L1+ with pricing)
   - RETAIN: total return visits (only if L3+)

2. Map event count to confidence level:
   - < 30 events: 'insufficient' — ratio shown with ⚠ marker, excluded from verdict logic
   - 30-100 events: 'directional' — ratio shown with ~ marker, used in verdict but flagged
   - 100-500 events: 'reliable' — ratio shown normally
   - 500+ events: 'high' — ratio shown with ✓ marker

3. Store in experiment_metric_snapshots alongside each dimension:
   { dimension: 'reach', ratio: 1.9, confidence: 'reliable', event_count: 523 }

4. Dimensions unavailable at current level:
   - L1: ACTIVATE and RETAIN → set to { ratio: null, confidence: 'unavailable' }
   - L2: RETAIN → set to { ratio: null, confidence: 'unavailable' }
   - 'unavailable' dimensions are NOT 'insufficient' — they display as "-- (requires L2)" not "⚠"

5. Guard clause uses confidence levels:
   - If ALL measured dimensions are 'insufficient' → no verdict (guard clause triggers)
   - If REACH is 'insufficient' → no verdict (need minimum traffic data)

npm run build 零错误。
```

---

## Phase 7: Polish

### Session 12a — CSS Tokens + 6 Mobile Components

**目标**：建立 CSS foundation 和 6 个 mobile components。

**输入**：Session 5-7 的所有页面

**输出**：
- CSS timing tokens + safe area variables + mobile utilities
- 6 个新 mobile components
- Breakpoint strategy + particles + swipe-to-archive

**输出合约**（Session 12b 验证）：
```
src/components/mobile-tab-bar.tsx         → exists (Bottom nav: Lab / New / Settings)
src/components/mobile-bottom-sheet.tsx    → exists (Draggable bottom sheet)
src/components/scrollable-tab-strip.tsx   → exists (Horizontal scrollable pills)
src/components/card-carousel.tsx          → exists (Snap-scroll cards)
src/components/pull-to-refresh.tsx        → exists (Custom pull-to-refresh)
src/components/sticky-action-bar.tsx      → exists (Bottom CTA + safe-area)
src/app/globals.css                       → contains --dur-instant, --ease-out-expo, --safe-top CSS variables
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/ux-design.md 的 Responsive & Mobile Design section（完整读完）。
读 docs/CONVENTIONS.md。

用 /change 实现 CSS foundation 和 mobile components：

## 1. CSS Foundation

在 globals.css 添加:

### Timing tokens（:root）
- Duration: --dur-instant(50ms), --dur-micro(100ms), --dur-fast(150ms), --dur-normal(250ms),
  --dur-emphasis(400ms), --dur-dramatic(600ms), --dur-ceremony(900ms), --dur-ambient(3000ms), --dur-float(4000ms)
- Easing: --ease-out-expo, --ease-out-back, --ease-in-out-sine, --ease-out-quart, --ease-in-expo, --ease-spring
  （具体 cubic-bezier / linear() 值来自 ux-design.md）
- Stagger: --stagger-item(60ms), --stagger-max(8), --stagger-cap(480ms)

### Safe area variables
- --safe-top, --safe-bottom, --safe-left, --safe-right
- --tab-bar-height: 56px
- --mobile-bottom-offset: calc(var(--tab-bar-height) + var(--safe-bottom))

### Mobile utilities
- .pb-safe, .pt-safe, .mb-tab
- .scrollbar-hide
- .touch-feedback:active（@media (pointer: coarse)）
- @media (prefers-reduced-motion: reduce) block

### Viewport
- meta viewport: width=device-width, initial-scale=1, viewport-fit=cover
- 使用 100dvh，不用 100vh
- overscroll-behavior-y: contain on body

## 2. Six New Mobile Components

| Component | File | Purpose |
|-----------|------|---------|
| MobileTabBar | src/components/mobile-tab-bar.tsx | Bottom nav: Lab / New / Settings |
| MobileBottomSheet | src/components/mobile-bottom-sheet.tsx | Draggable bottom sheet |
| ScrollableTabStrip | src/components/scrollable-tab-strip.tsx | Horizontal scrollable pills |
| CardCarousel | src/components/card-carousel.tsx | Snap-scroll cards + dot indicators |
| PullToRefresh | src/components/pull-to-refresh.tsx | Custom pull-to-refresh |
| StickyActionBar | src/components/sticky-action-bar.tsx | Bottom CTA + safe-area |

MobileTabBar specs:
- Height: 56px + env(safe-area-inset-bottom)
- bg-background/90 backdrop-blur-xl border-t
- 3 tabs: Lab (🧪), New (✨), Settings (⚙️)
- Active: primary color icon + label; inactive: muted icon only
- Hidden when keyboard open（visualViewport API）
- z-index: 50

## 3. Breakpoint Strategy

| Token | Width | Changes |
|-------|-------|---------|
| < sm | < 640px | Single column, full-width CTAs, bottom tab bar |
| sm | ≥ 640px | Inline CTAs, labels visible |
| md | ≥ 768px | Multi-column, top nav, particles ON |
| lg | ≥ 1024px | Full desktop density |
| xl | ≥ 1280px | max-w-7xl centered |

Particles OFF below md. Hover OFF below md（use :active instead）。
Touch targets min 44×44px。

Particles 实现:
- Desktop (md+): Landing page 环境粒子使用 CSS-only `@keyframes float` on `::before`/`::after` pseudo-elements（不用 `<canvas>` — ux-design.md 指定 "CSS gradient mesh"）。SCALE verdict 庆祝使用 `canvas-confetti` npm 包（3KB gzip）。所有粒子元素 `aria-hidden="true"` + `pointer-events: none`。
- Mobile (<md): 无粒子。Verdict celebration 使用 color gradient background transition 替代。

Swipe-to-archive 实现:
- Lab experiment cards 使用 touch event handlers（`touchstart`/`touchmove`/`touchend`）+ `transform: translateX()` 实现 swipe-left-to-archive。卡片滑动后露出红色 "Archive" action strip。Threshold: 卡片宽度 30% 触发 archive。不创建独立 SwipeableCard 组件 — inline 在 Lab card component 中实现。Container 使用 `overflow: hidden`。

## Mobile Lab Enhancement

1. Add Portfolio Health Score (★ XX) to the right side of the mobile Lab header
2. Replace state-based grouping (RUNNING/VERDICT/COMPLETED) with urgency-based grouping:
   - "NEEDS ATTENTION": experiments where score < 20 OR status = verdict_ready OR budget fully spent
   - "ON TRACK": all other running experiments
   - "COMPLETED": completed/archived experiments (collapsed by default)
3. NEEDS ATTENTION cards: include inline action buttons [Kill & Free Budget] [View ->]
4. ON TRACK cards: compressed layout — name + ★ score + one-line status only
5. Pull-to-refresh on Lab page triggers metrics sync for each running experiment via POST /api/experiments/:id/metrics/sync (score recomputation is part of the sync pipeline)

npm run build 零错误。
```

---

### Session 12b — Animation Choreography + Per-Page Mobile

**目标**：实现 animation choreography 和 per-page mobile wireframes。

**输入**：Session 12a 的 CSS foundation + mobile components

**输出**：
- Per-page mobile wireframe implementation
- Animation choreography sequences（A, B, C）
- Per-verdict modulation

**输出合约**（Session 12c 验证）：
```
Animation Sequence A (Spec Materializing): verify via grep for "skeleton" + "crossfade" + "stagger" in assay/page.tsx
Animation Sequence B (Verdict Reveal): verify via grep for "verdict" + "spring" + "confetti" in verdict/[id]/page.tsx
Per-page mobile wireframes: all 8 pages have responsive breakpoints (grep for "sm:" or "md:" in each page.tsx)
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/ux-design.md 的 Animation Timing System section（完整读完）。
读 docs/CONVENTIONS.md。

用 /change 实现 animation choreography + per-page mobile：

## 1. Per-Page Mobile Wireframes

实现 ux-design.md 中每个 page 的 mobile wireframe:

- Landing mobile: static CSS gradient（no canvas）, text-4xl, full-width CTA h-14, vertical pain points, vertical how-it-works, 2×2 stats grid
- Assay mobile: accordion sections（one at a time）, variant card carousel 280px
- Experiment detail mobile: full-width vertical scorecard bars, scrollable pill tabs
- Lab mobile: full-width card stack, 4px left border color, pull-to-refresh, FAB, swipe-left archive
- Settings mobile: scrollable tab strip, single-column pricing plans
- Verdict mobile: text-5xl centered, fills viewport, scroll for details, no particles

## 2. Animation Choreography

### Sequence A: Spec Materializing（~3200ms）
t=0: skeleton visible
t=0: name crossfade (swap, 250ms)
t=200: pre-flight icons pop (scale-in, 150ms, ease-out-back, 300ms stagger)
t=1500: hypothesis cards stagger (fade-up, 400ms, 60ms stagger)
t=2300: variant cards (fade-up, 400ms, 100ms stagger)
t=2800: cost counters animate (ease-out-quart, 400ms)
t=3200: edit icons + buttons fade in

### Sequence B: Verdict Reveal（~3600ms）
t=0: previous content exits (fade-out, 150ms)
t=300: colored background fades in
t=400: verdict icon springs (scale 0→1, ease-spring, 600ms)
t=700: verdict word (letter-spacing contracts, 600ms)
t=1100: subtitle fades in
t=1500: scorecard bars fill (scaleX, 600ms, ease-out-quart, 200ms stagger)
t=2400: ROI summary fades up
t=2800: recommendation fades up
t=3200: action buttons appear
t=3600: CTA glow begins

Per-verdict modulation:
- SCALE: confetti at t=400 (desktop only)
- KILL: 15% slower, "You saved 3 months" underline
- REFINE: bottleneck bar pulses
- PIVOT: icon oscillates ±5px

### Sequence C: Scorecard Bar Update（~1200ms）
Previous → new value transition via scaleX。Color shift at 1.0x threshold。

npm run build 零错误。
```

---

### Session 12c — Visual Verification

**目标**：实现 reduced motion support、performance budget、visual verification pass。

**输入**：Session 12b 的 animation + mobile wireframes

**输出**：
- Reduced motion support
- Performance budget enforcement
- Visual verification（screenshot → compare to wireframe → fix）

**输出合约**（Session 13 验证）：
```
@media (prefers-reduced-motion: reduce) block in globals.css
Performance budget: no width animations on scorecard bars (verify scaleX usage)
Visual verification pass completed for all 8 pages (desktop 1280px + mobile 375px)
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

读 docs/ux-design.md 的 Responsive & Mobile Design section（Reduced Motion 和 Performance Budget 部分）。
读 docs/CONVENTIONS.md。

用 /change 实现 reduced motion + performance + visual verification：

## 1. Reduced Motion

@media (prefers-reduced-motion: reduce):
- REMOVE: pulse-glow, float, particles, confetti, letter-spacing, stagger delays
- REPLACE: entrances → opacity 0→1 in 1ms, bars → jump, counters → instant
- KEEP: hover colors, shimmer (slowed), focus rings, color transitions (250ms)

useRevealOnScroll hook: check matchMedia, skip IntersectionObserver if reduced motion。

## 2. Performance Budget

- Max 12 simultaneous animations
- GPU-only: transform + opacity
- Scorecard bars: scaleX（never width）
- will-change: set on trigger, remove on animationend
- Mobile: halved stagger, reduced translateY (8px), shorter durations

## 3. Visual Verification Pass

对每个页面执行视觉验证：
a. 截取 desktop (1280px) 和 mobile (375px) screenshots
b. 对比 ux-design.md 中的 ASCII wireframes
c. 检查：布局对齐、间距一致、颜色正确、字体大小、touch targets ≥ 44px
d. 修复偏差

关注点：
- Landing page above-the-fold 只有一个输入框（不能有 noise）
- Verdict page fills viewport（no scroll needed for verdict word）
- Lab cards 信息密度正确（ONE number per card）
- Experiment page scorecard bars 使用 scaleX（not width）
- Mobile tab bar 在 keyboard open 时隐藏

npm run build 零错误。
```

---

### [CP5] Checkpoint: Complete Application

**验证范围**：Sessions 1-12c 的全部输出（完整应用）。

**检查项**：
1. `npm run build` 零错误
2. `npx tsc --noEmit` 零错误
3. `npm test` 通过
4. 所有 8 个页面 desktop + mobile 渲染无错误
5. 6 个 mobile components 存在且功能正常
6. CSS timing tokens 存在于 globals.css
7. Animation sequences A/B/C 可触发
8. Reduced motion 模式下动画正确降级
9. 所有 API routes 返回正确 HTTP status
10. Cron routes 存在（metrics-sync, cleanup, notifications, cost-monitor, hosting-billing, compute-scores, generate-insights, auto-rebalance）
11. Docker image spec 存在
12. 所有环境变量在 .env.example 中记录（包括 VAPID keys for browser push）
13. Browser push: public/sw.js 存在，src/lib/push-notifications.ts exports requestPushPermission
14. `quality: production` — ALL behaviors (b-01~b-29) 的 `tests` 条目 100% 有对应 spec test 或 Playwright assertion。这是进入 /harden 前的最终覆盖验证。

**输出**：CP5 verification report。这是最终 checkpoint — 修复所有问题后进入 /harden + /verify。

**Prompt**:

```
执行 [CP5] Checkpoint: Complete Application。

验证范围：Sessions 1-12c 的全部输出（完整应用）。

步骤：

1. 运行自动化检查：
   - `npm run build`（零错误）
   - `npx tsc --noEmit`（零错误）
   - `npm test`（全部通过）
   如有失败，修复后重新运行，最多 3 次。

2. 完整应用验证：
   - 确认 8 个页面 desktop + mobile 渲染无错误
   - 确认 6 个 mobile components 存在且功能正常
   - 确认 CSS timing tokens、Animation sequences、Reduced motion
   - 确认所有 API routes + Cron routes
   - 确认 Docker image spec 存在
   - 确认所有环境变量在 .env.example 中记录

3. behavior.tests 100% 覆盖验证（quality: production，最终验证）：
   读 experiment/experiment.yaml 中 ALL behaviors b-01 到 b-29。
   对每个 behavior 的每一条 tests 条目，确认有对应测试：
   - API behaviors → vitest spec test assertion
   - UI behaviors → Playwright smoke/funnel assertion
   - System/cron behaviors → vitest flows.test.ts assertion
   - Payment flows (b-22, b-23, b-25) → 深度 spec test（验证 handler 逻辑）
   生成覆盖矩阵表（behavior ID | tests 条目 | 对应测试文件:行号 | 状态）。
   缺失的覆盖：补上。补完后重新运行 npm test 确认通过。

4. 生成 checkpoint report 写入 docs/cp5-report.md。
   这是最终 checkpoint — 所有检查项必须通过后才能进入 /harden + /verify。

所有检查项通过后，报告结果。
```

---

## Phase 8: Quality + Deploy

### Session 13 — /harden + /verify

**目标**：加固和验证。

**输入**：Session 1-12 的完整代码

**输出**：
- Security hardening（RLS 审查、input validation、rate limiting 审查）
- Specification tests for critical paths
- E2E tests passing
- Build passing

**输出合约**（Session 14 验证）：
```
.github/workflows/ci.yml    → exists with build, typecheck, vitest, playwright jobs
npm run build                → zero errors
npx tsc --noEmit             → zero errors
npx vitest run               → all tests pass
npx playwright test          → all tests pass
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

## Pre-harden: Sentry Error Monitoring

1. npm install @sentry/nextjs
2. npx @sentry/wizard@latest -i nextjs
3. .env.example 添加 SENTRY_DSN, SENTRY_AUTH_TOKEN
4. npm run build 通过

## Pre-harden: GitHub Actions CI

创建 `.github/workflows/ci.yml`:
- Trigger: pull_request to main
- Jobs: build, lint, typecheck, vitest, playwright
- Steps:
  1. Checkout + setup Node 20 + npm ci
  2. `npm run build` — zero errors
  3. `npx tsc --noEmit` — typecheck
  4. `npx vitest run` — unit/spec tests
  5. `npx playwright install --with-deps && npx playwright test` — E2E tests
- Environment: use `.env.example` values + test-specific overrides
- Playwright 使用 `npx playwright install --with-deps` 安装 browsers in CI
- Cache: node_modules + .next/cache + playwright browsers

然后运行 /harden。

Harden 完成后，运行 /verify。

关注的 critical paths（quality: production 要求 spec tests）:
- Auth flow（signup, login, token refresh）
- Billing flow（authorize → execute → complete, PAYG deduction, pool management）
- Spec streaming（SSE protocol, anonymous spec storage, claim）
- Skill execution（trigger → progress → gate → approve → complete）
- Metrics sync（scorecard computation, alert detection, verdict engine）

/verify 应该并行运行 6 个 agents:
1. behavior-verifier
2. security-defender
3. security-attacker
4. accessibility-scanner
5. performance-reporter
6. spec-reviewer（quality: production 额外添加）

修复所有发现的问题，直到 build + tests 全部通过。

npm run build 零错误。npx vitest run 通过。npx playwright test 通过。
```

---

### Session 14 — /deploy + Validation

**目标**：部署到 production 并验证。

**输入**：Session 13 的 hardened code

**输出**：
- 部署到 Vercel（assayer.io）
- Supabase production 配置
- 环境变量全部配置
- Smoke test 通过

**输出合约**（Post-deploy 验证）：
```
assayer.io                   → Landing page loads
SSE spec stream              → returns events for test idea
Supabase RLS                 → enforced on all tables
Stripe webhook               → reachable
Cron jobs                    → registered in Vercel
```

**Prompt**:

```
先读 docs/assayer-session-prompts.md 中本 session 的「输出合约」和前序 session 的「输出合约」，执行文件顶部 "Session Preamble Template" 中的合约验证步骤。

运行 /deploy。

部署前确认所有环境变量已在 .env.example 中记录:

## Supabase
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY

## Auth (Supabase handles, but need OAuth apps configured)
# Google OAuth: configured in Supabase dashboard
# GitHub OAuth: configured in Supabase dashboard

## Analytics
NEXT_PUBLIC_POSTHOG_KEY
NEXT_PUBLIC_POSTHOG_HOST

## AI
ANTHROPIC_API_KEY

## Payments
STRIPE_SECRET_KEY
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY
STRIPE_WEBHOOK_SECRET
STRIPE_PRO_PRICE_ID
STRIPE_TEAM_PRICE_ID

## Cloud Run Jobs
GCP_PROJECT_ID
GCP_REGION
CLOUD_RUN_JOB_NAME
GCP_SA_KEY

## Railway (for AI agent / long-running experiments)
RAILWAY_TOKEN

## Distribution
TWITTER_CLIENT_ID
TWITTER_CLIENT_SECRET
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
RESEND_API_KEY
GOOGLE_ADS_MCC_ID
GOOGLE_ADS_CLIENT_ID
GOOGLE_ADS_CLIENT_SECRET
GOOGLE_ADS_DEVELOPER_TOKEN
META_APP_ID
META_APP_SECRET
TWITTER_ADS_CONSUMER_KEY
TWITTER_ADS_CONSUMER_SECRET

## Cron
CRON_SECRET

## DNS (Railway experiments)
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ZONE_ID

## Push Notifications (browser push, opt-in)
NEXT_PUBLIC_VAPID_PUBLIC_KEY
VAPID_PRIVATE_KEY
VAPID_SUBJECT

## Monitoring
SENTRY_DSN
SENTRY_AUTH_TOKEN

部署后验证:
1. Landing page 加载（assayer.io）
2. SSE spec stream 工作（输入 idea → 看到 events）
3. Signup 流程（Google/GitHub OAuth + email）
4. Spec claim 成功
5. Lab page 渲染
6. Settings page 渲染
7. Stripe webhook 可达
8. Supabase RLS 生效
9. Cron jobs 注册
10. Railway CLI 认证成功（`railway whoami`）
11. 创建测试 Railway project 验证 token 有效

如果任何验证失败，修复并重新部署。
```

---

## Appendix: 完整性审查

### Pages（8 pages，来自 product-design.md Section 6）

| Page | Session | Route |
|------|---------|-------|
| landing | S5 | / |
| assay | S5 | /assay |
| launch | S6a | /launch/[id] |
| experiment | S6b | /experiment/[id] |
| verdict | S7 | /verdict/[id] |
| lab | S7 | /lab |
| compare | S7 | /compare |
| settings | S7 | /settings |

### API Routes（~55 routes，来自 product-design.md Section 5）

| Route Group | Session | Routes |
|-------------|---------|--------|
| Spec (anonymous) | S4 | POST /api/spec/stream, POST /api/spec/claim |
| Experiments CRUD | S3 | GET/POST/PATCH/DELETE /api/experiments, GET /api/experiments/:id |
| Hypotheses | S3 | POST/GET /api/experiments/:id/hypotheses |
| Variants | S3 | POST/GET /api/experiments/:id/variants |
| Insights | S3 | POST/GET /api/experiments/:id/insights |
| Research | S3 | POST/GET /api/experiments/:id/research |
| Rounds | S3 | GET/POST /api/experiments/:id/rounds |
| Metrics | S11 | POST /api/experiments/:id/metrics/sync(?force_verdict=true), GET /api/experiments/:id/metrics |
| Metrics Export | S7 | GET /api/experiments/:id/metrics/export (CSV download) |
| Skills | S9a | POST /api/skills/execute, GET /api/skills/:id, POST /api/skills/:id/approve, POST /api/skills/:id/cancel |
| Distribution | S10 | GET /api/experiments/:id/distribution, POST .../sync, POST .../manage |
| Distribution Plan | S10 | POST /api/experiments/:id/distribution/plan |
| Distribution OAuth | S10 | GET /api/distribution/callback/{twitter,reddit,google-ads,meta,twitter-ads} |
| Alerts | S11 | GET /api/experiments/:id/alerts, PATCH .../alerts/:alertId |
| Compare | S7 | GET /api/experiments/compare |
| Billing | S8, S9a | POST /api/operations/authorize, POST .../complete, POST /api/operations/:id/extend, GET /api/billing/usage, POST .../subscribe, POST .../topup, POST .../portal |
| Portfolio Intelligence | S7, S11 | GET /api/portfolio/insight, POST .../insight/:id/apply, POST .../insight/:id/dismiss, GET /api/portfolio/budget, POST .../budget/allocate |
| Notifications | S11 | GET /api/notifications, PATCH /api/notifications/:id, POST /api/notifications/mark-all-read, POST /api/notifications/push-subscribe |
| Webhooks | S8 | POST /api/webhooks/stripe |
| Cron | S8, S11 | /api/cron/metrics-sync, /api/cron/cleanup, /api/cron/notifications, /api/cron/cost-monitor, /api/cron/hosting-billing, /api/cron/compute-scores, /api/cron/generate-insights, /api/cron/auto-rebalance |

### DB Tables（20 tables，来自 product-design.md Section 6 + Portfolio Intelligence + Push Notifications）

| Table | Session |
|-------|---------|
| anonymous_specs | S3 |
| experiments | S3 |
| experiment_rounds | S3 |
| hypotheses | S3 |
| hypothesis_dependencies | S3 |
| research_results | S3 |
| variants | S3 |
| experiment_metric_snapshots | S3 |
| experiment_decisions | S3 |
| experiment_alerts | S3 |
| notifications | S3 |
| ai_usage | S3 |
| user_billing | S3 |
| operation_ledger | S3 |
| skill_executions | S3 |
| oauth_tokens | S3 |
| distribution_campaigns | S3 |
| portfolio_insights | S3 |
| budget_allocations | S3 |
| push_subscriptions | S11 |

### Environment Variables（S14 deploy checklist 列出全部）

| Category | Variables | Session |
|----------|-----------|---------|
| Supabase | NEXT_PUBLIC_SUPABASE_URL, ANON_KEY, SERVICE_ROLE_KEY | S2 |
| Analytics | NEXT_PUBLIC_POSTHOG_KEY, HOST | S2 |
| AI | ANTHROPIC_API_KEY | S4 |
| Payments | STRIPE_SECRET_KEY, PUBLISHABLE_KEY, WEBHOOK_SECRET, PRO_PRICE_ID, TEAM_PRICE_ID | S8 |
| Cloud Run | GCP_PROJECT_ID, REGION, JOB_NAME, SA_KEY | S9a |
| Distribution (organic) | TWITTER_CLIENT_ID/SECRET, REDDIT_CLIENT_ID/SECRET, RESEND_API_KEY | S10 |
| Distribution (paid) | GOOGLE_ADS_*, META_*, TWITTER_ADS_* | S10 |
| Cron | CRON_SECRET | S11 |
| DNS | CLOUDFLARE_API_TOKEN, CLOUDFLARE_ZONE_ID | S9b |
| Push Notifications | NEXT_PUBLIC_VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT | S11 |
| Monitoring | SENTRY_DSN, SENTRY_AUTH_TOKEN | S13 |

### UX Flows Covered

| Flow (product-design.md) | Session |
|--------------------------|---------|
| Flow 1: Idea → Spec (SSE) | S4, S5 |
| Flow 2: Signup Gate → Spec Recovery | S5 |
| Flow 3: Build → Deploy → Distribute | S6a, S9a, S9b, S10 |
| Flow 4: Metrics Sync + Scorecard + Alerts | S11 |
| Flow 5: Verdict → Return Flows | S7, S11 |
| Flow 6: /iterate Skill (per-hypothesis verdicts) | S11 |

### UX Screens Covered

| Screen (ux-design.md) | Session |
|------------------------|---------|
| Screen 1: Landing | S5 |
| Screen 2: The Assay (creation + edit mode) | S5 |
| Screen 3: Signup Gate (+ TOTP 2FA) | S5 |
| Screen 5: Build & Launch | S6a |
| Screen 6: Experiment Page | S6b |
| Screen 7: Verdict | S7 |
| Screen 7a: Return Flows | S7 |
| Screen 8: Lab | S7 |
| Screen 9: Settings | S7 |
| Experiment Comparison | S7 |
| Error & Edge States | S6b (alert banners) |
| Notifications | S11 |
| Responsive & Mobile | S12a, S12b |
| Animation Timing | S12b, S12c |

### Checkpoint Coverage Matrix

| Checkpoint | Verifies Sessions | Key Focus |
|------------|-------------------|-----------|
| [CP1] | S1-S4 | Data layer + API foundation |
| [CP2] | S5-S6b | UI pages + SSE streaming |
| [CP3] | S5-S8 | Full UI + billing integration |
| [CP4] | S9a-S10 | Skill execution + distribution |
| [CP5] | S1-S12c | Complete application (pre-harden) |
