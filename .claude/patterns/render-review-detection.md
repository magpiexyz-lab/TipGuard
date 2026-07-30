# Render-Review Detection

Detection procedure for agents that navigate auth-gated routes in demo mode
and must distinguish a real render from a redirect / skeleton / navigation
failure. Prevents per-page reviewers from silently issuing `pass` verdicts
when the target page was never actually rendered.

> Called by:
> - `.claude/procedures/design-critic.md` (per page, before screenshot)
> - `.claude/procedures/accessibility-scanner.md` (per page, inside R1 loop)

## Inputs

Caller passes an options object to the inline detection script:

- `browser`: a live Playwright `Browser` instance the caller already
  created with `chromium.launch({ headless: true })`. The pattern creates a
  new `BrowserContext` off it — never a new browser.
- `requested_route`: path being reviewed (e.g. `"/dashboard"`)
- `base_url`: dev server URL the caller already started (e.g. `"http://localhost:3099"`)
- `is_first_page`: boolean — when `true` and URL bypass fails into an auth
  route, the detection marks `fallback_reason="demo-mode-bypass-failed"` so
  the loud upstream middleware/env bug surfaces exactly once per run.
  When `auth_requirement="anonymous"` the diagnostic is suppressed regardless
  of `is_first_page` (anonymous journeys have no auth bypass to fail).
- `route_pattern` (optional, default `= requested_route`): literal route
  template from `.runs/design-page-set.json` (e.g. `"/quote/[id]"`). Callers
  pass this separately from `requested_route` when they concretize dynamic
  segments with synthetic IDs (nil UUID etc.) before navigation. Required
  for the DEMO_MODE fixture short-circuit branch in Section 3 — a 404 on a
  concrete URL must trace back to a bracket-containing pattern to qualify.
- `demo_mode` (optional, default `false`): boolean indicating DEMO_MODE is
  active (agent runs against `DEMO_MODE=true` dev server). Required `true`
  for the DEMO_MODE fixture short-circuit branch; detected from
  `process.env.DEMO_MODE === "true"` at the caller level so the detection
  remains pure.
- `expected_destination` (optional, default `= requested_route`): pathname the
  URL-mismatch gate compares against after settle. Per-page reviewers leave this
  unset (detection collapses to current semantics). Per-step reviewers pass
  the step's **declared destination** so that a click-to-login flow (origin `/`,
  expected `/login`, final `/login`) classifies as `rendered-*` rather than
  `source-only`.
- `auth_requirement` (optional, default `"optional"`): one of:
  - `"anonymous"` — plain context, skip storageState injection entirely. Use for
    anonymous user flows that must not inherit a prior session.
  - `"optional"` — **current default behavior, byte-identical to pre-change**.
    Attempt storageState load; fall back to demo-mode on any failure.
  - `"required"` — storageState is mandatory. If `e2e/.auth.json` is absent,
    malformed, or lacks a Supabase cookie, detection short-circuits with
    `review_method="prereq-unmet"` and never calls `page.goto()`. Use for
    reviewers whose correctness depends on an authenticated session (e.g.,
    `behavior-verifier` on behaviors with `given: "logged-in user"`).

## Caller cleanup

The returned `context` (and therefore `page`) is live when the pattern
returns. The caller MUST call `await context.close()` before moving to the
next page to avoid leaking contexts. See accessibility-scanner.md R1 for
the per-page `finally`/explicit-close pattern; design-critic reuses the
context through Step 4's screenshot loop and closes it at the end of Step
7 cleanup.

## Outputs

Returned as a JS object. The caller merges it into the agent's trace.

- `review_method`: `"rendered-authed" | "rendered-demo" | "source-only" | "unknown" | "prereq-unmet"`
  - Session C / #1042: when the classifier lands in `"source-only"` because
    of a DEMO_MODE fixture short-circuit on a dynamic route (HTTP 404 +
    DEMO_MODE on + route_pattern has `[segment]`), it stamps
    `fallback_reason="demo-mode-fixture-short-circuit"`. Downstream
    design-critic emits a self-degraded trace (see `.claude/agents/design-critic.md`
    "Rendered-Review Contract"); no new review_method enum value is added.
  - `"prereq-unmet"` is emitted **only** when `auth_requirement="required"` and
    the storageState precondition fails. It is a first-class skip verdict —
    callers must map it to their own skip-semantics (e.g., behavior-verifier
    → `"SKIPPED"`, ux-journeyer → `"blocked"`). It is **never** emitted when
    `auth_requirement ∈ {"optional", "anonymous"}`.
- `review_evidence`:
  - `requested_route`: string (echo of input)
  - `final_url`: string (`page.url()` after settle); `null` when detection
    short-circuited on `prereq-unmet` before navigation.
  - `auth_source`: `"storageState" | "demo-mode" | null`
  - `fallback_reason`: string | null (e.g. `"redirected-to-auth-route"`,
    `"demo-mode-bypass-failed"`, `"storageState-load-failed"`, `"auth.json-no-cookies"`,
    `"auth.json-absent"` (only in `auth_requirement="required"` branch),
    `"demo-mode-fixture-short-circuit"` (Session C #1042: HTTP 404 on a
    dynamic-segment route with DEMO_MODE on — see Section 3 DEMO_MODE branch))
  - `final_status`: integer | null — HTTP status code of the initial
    `page.goto()` response. Populated when the navigation completes; `null`
    when `navError` fires or `prereq-unmet` short-circuits before goto.
  - `route_pattern`: string | null — echo of the caller-supplied
    `route_pattern` (literal `"/quote/[id]"` form). Present on every
    classification for downstream auditing; `null` if caller omitted.
  - `content_density`: number | null (observational only; NOT gated in this change)
  - `expected_destination`: string | null — echo of the caller-supplied
    `expected_destination`. `null` when the caller relied on the default
    (`= requested_route`). Surfaces the per-step/per-behavior declaration
    in the trace so downstream consumers can tell apart "caller asserted
    origin==destination" from "caller declared a different destination".

## Section 1 — storageState injection (branches by `auth_requirement`)

Before creating a BrowserContext, branch on `auth_requirement`:

| `auth_requirement` | Behavior |
|---|---|
| `"anonymous"` | Skip storageState entirely; always create a plain context. `authSource = "demo-mode"`. No `fallback_reason` set from this section. |
| `"optional"` (default) | **Current behavior, byte-identical to pre-change.** Try storageState; fall back to plain context on any failure. |
| `"required"` | Load storageState. On failure, set `reviewMethodEarly = "prereq-unmet"` and `fallbackReason = <storageState reason>` and **skip navigation** entirely. Caller still owns `context.close()`. |

```javascript
const fs = require("fs");
const AUTH_FILE = "e2e/.auth.json";
const auth_requirement = opts.auth_requirement || "optional";

function tryLoadStorageState() {
  if (!fs.existsSync(AUTH_FILE)) return { ok: false, reason: "auth.json-absent" };
  let data;
  try {
    data = JSON.parse(fs.readFileSync(AUTH_FILE, "utf-8"));
  } catch {
    return { ok: false, reason: "auth.json-parse-failed" };
  }
  if (!Array.isArray(data.cookies) || data.cookies.length === 0) {
    return { ok: false, reason: "auth.json-no-cookies" };
  }
  if (!data.cookies.some((c) => /^sb-.*-auth-token/.test(c.name || ""))) {
    return { ok: false, reason: "auth.json-no-supabase-cookie" };
  }
  return { ok: true };
}
```

Create the context:

```javascript
let authSource = "demo-mode";
let fallbackReason = null;
let reviewMethodEarly = null;  // non-null ONLY when auth_requirement="required" + storageState fails
let context;

if (auth_requirement === "anonymous") {
  // Explicit opt-out: never inject storageState, even if .auth.json is valid.
  // Used by anonymous user flows (ux-journeyer starting on /) to avoid
  // inheriting a prior session that would change which CTA is visible.
  context = await browser.newContext();
} else {
  const storageStateCheck = tryLoadStorageState();

  if (auth_requirement === "required" && !storageStateCheck.ok) {
    // Short-circuit: the caller's correctness depends on auth. Signal
    // prereq-unmet so the caller can skip (not fail) this review.
    context = await browser.newContext();  // still return a usable context for cleanup symmetry
    reviewMethodEarly = "prereq-unmet";
    fallbackReason = storageStateCheck.reason;
  } else if (storageStateCheck.ok) {
    try {
      context = await browser.newContext({ storageState: AUTH_FILE });
      authSource = "storageState";
    } catch (err) {
      context = await browser.newContext();
      fallbackReason = "storageState-load-failed";
    }
  } else {
    // auth_requirement === "optional" AND storageState not ok: fall back
    // to demo-mode (current behavior).
    context = await browser.newContext();
    // Only record a fallback_reason when something UNEXPECTED caused the
    // fallback. Absence of e2e/.auth.json is the default in bootstrap — not
    // a fallback, just the normal demo-mode path. Recording it here would
    // pollute every bootstrap trace. Other reasons (parse failure, missing
    // cookies on a file that DID exist, etc.) ARE fallbacks worth recording.
    if (storageStateCheck.reason !== "auth.json-absent") {
      fallbackReason = storageStateCheck.reason;
    }
  }
}
```

## Section 2 — Navigate with settle wait

`networkidle` alone is not enough — client-side `useEffect` auth redirects
may fire after networkidle settles. Wait 500 ms extra before reading the URL:

```javascript
const page = await context.newPage();
let navError = null;
let finalStatus = null;  // HTTP status from initial goto response (#1042)
try {
  const response = await page.goto(
    base_url + requested_route,
    { waitUntil: "networkidle", timeout: 15000 },
  );
  finalStatus = response ? response.status() : null;
  await page.waitForTimeout(500);
} catch (err) {
  navError = err.message;
}
```

## Section 3 — Classify review_method

The URL-mismatch gate compares `page.url()`'s pathname against
`expected_destination ?? requested_route`. Per-page reviewers leave
`expected_destination` unset, so the gate collapses to the current
`finalPath !== requested_route` semantic (byte-identical). Per-step /
per-behavior reviewers pass their declared destination so that
click-to-login / expected-redirect flows don't mis-classify as `source-only`.

```javascript
// SHARED:AUTH_PATHS — canonical list. ALSO referenced by
// .claude/patterns/review-verdict-gate.md. Any change here requires a
// matching update in that file. The drift test at
// .claude/scripts/tests/test_auth_paths_drift.py enforces equality.
const AUTH_PATHS = new Set(["/login", "/signup", "/auth/callback", "/auth/reset-password"]);

const expected_destination = opts.expected_destination || null;
const expectedPath = expected_destination || requested_route;
const route_pattern = opts.route_pattern || requested_route;
const demo_mode = opts.demo_mode === true;
// Dynamic segment detection — any [bracket] substring in the route pattern
// qualifies. Covers /[id], /[slug], /[...catchall], /[[...optional]].
const hasDynamicSegment = /\[[^\]]+\]/.test(route_pattern);

let reviewMethod;
let finalUrl = null;
let finalPath = null;

if (navError) {
  reviewMethod = "unknown";
  fallbackReason = `navigation-failed:${navError}`;
} else if (finalStatus === 404 && demo_mode && hasDynamicSegment) {
  // Session C / #1042: DEMO_MODE fixture short-circuit.
  // Next.js notFound() preserves the URL but returns a 404 response, so the
  // URL-mismatch gate below would misclassify this as `rendered-*`. We
  // catch it here: any 404 on a dynamic-segment route under DEMO_MODE is
  // deterministically attributable to the Supabase stub returning null
  // from .single() / .maybeSingle() for the synthetic fixture ID (see
  // .claude/scripts/lib/derive_pages.py synthetic-ID table). A 404 on a
  // STATIC route stays a genuine bug and falls through to the
  // URL-mismatch branch.
  reviewMethod = "source-only";
  fallbackReason = "demo-mode-fixture-short-circuit";
  finalUrl = page.url();
  try { finalPath = new URL(finalUrl).pathname; } catch { finalPath = null; }
} else {
  finalUrl = page.url();
  try { finalPath = new URL(finalUrl).pathname; } catch { finalPath = null; }

  if (finalPath !== expectedPath) {
    reviewMethod = "source-only";
    if (AUTH_PATHS.has(finalPath)) {
      // `demo-mode-bypass-failed` is the "first auth-gated route got bounced
      // to login" diagnostic — it fires exactly once per run to surface an
      // upstream middleware/env bug. Suppress entirely when the caller
      // explicitly declared an anonymous journey: there's no auth bypass
      // to fail in that case.
      if (auth_requirement === "anonymous") {
        fallbackReason = "redirected-to-auth-route";
      } else {
        fallbackReason = is_first_page ? "demo-mode-bypass-failed" : "redirected-to-auth-route";
      }
    } else {
      fallbackReason = `redirected:${finalPath ?? "unknown"}`;
    }
  } else if (authSource === "storageState") {
    reviewMethod = "rendered-authed";
  } else {
    reviewMethod = "rendered-demo";
  }
}
```

Note: `auth.json-*` preconditions from Section 1 are INFORMATIONAL (in the
`"optional"` branch) — they do NOT force `review_method = "source-only"`.
They only block claiming `"rendered-authed"`. When cookies are absent we
still review the page in demo mode; that is normal for bootstrap.

In the `"required"` branch, Section 1 may have already set
`reviewMethodEarly = "prereq-unmet"`. When that is non-null, Sections 2
and 3 are **skipped entirely** and the caller returns with
`review_method = "prereq-unmet"`. See the `detectRenderAt` wrapper in
Section 6 for the guard.

## Section 4 — Content density (observational)

```javascript
let contentDensity = null;
if (reviewMethod === "rendered-demo" || reviewMethod === "rendered-authed") {
  try {
    contentDensity = await page.evaluate(() => {
      const sub = (sel) => document.querySelector(sel)?.innerText?.length ?? 0;
      const body = document.body?.innerText?.replace(/\s+/g, " ").trim().length ?? 0;
      return body - sub("header") - sub("nav") - sub("footer");
    });
  } catch {
    contentDensity = null;
  }
}
```

Not gated in this change. Surfaces in the trace for downstream analysis and
future tightening once real-data thresholds are known.

## Section 5 — Return shape

```javascript
return {
  review_method: reviewMethod,
  review_evidence: {
    requested_route,
    final_url: finalUrl,
    auth_source: authSource,
    fallback_reason: fallbackReason,
    content_density: contentDensity,
    expected_destination,  // echo of opts.expected_destination, null when caller defaulted
    final_status: finalStatus,  // HTTP status from initial goto (#1042)
    route_pattern: opts.route_pattern || null,  // echo of literal route (#1042)
  },
  context,  // caller reuses this context for screenshot / axe scan
  page,
};
```

**Backward-compat invariant**: when the caller passes no `expected_destination`,
no `auth_requirement`, no `route_pattern`, and no `demo_mode` (all default),
this return object is **field-compatible** with the pre-change pattern. The
added `final_status` + `route_pattern` fields default to `null` when the
caller omits them, and all existing callers that read `review_method` /
`review_evidence.{requested_route,final_url,auth_source,fallback_reason,content_density,expected_destination}`
continue to work unchanged.

## Section 6 — Callable units

This pattern is consumable in three shapes. Callers import the one that
matches their navigation semantic; the wrapper preserves the pre-change
entry point for current callers.

### 6.1 — `setupAuthContext(browser, opts)`

Runs Section 1. Returns:

```javascript
{ context, authSource, fallbackReason, reviewMethodEarly }
```

`reviewMethodEarly` is `"prereq-unmet"` when `auth_requirement="required"`
and storageState failed; otherwise `null`. The caller **must still close
`context`** even on `prereq-unmet` (symmetric cleanup).

### 6.2 — `detectRenderAt(context, opts)`

Runs Section 2 (navigate via `page.goto`) + Section 3 (classify) + Section 4
(content density). For per-page reviewers that want the detection to
perform its own navigation. Returns:

```javascript
{ review_method, review_evidence, page }
```

### 6.3 — `classifyCurrentPage(context, page, opts)`

Runs **only Section 3's classification** on an already-navigated page.
For reviewers whose navigation is interaction-driven (click, keyboard,
form submit) — ux-journeyer is the canonical caller. Does not call
`page.goto()`. Assumes the caller has already awaited `networkidle` +
any additional settle time. Returns:

```javascript
{ review_method, review_evidence }
```

### 6.4 — `renderReviewDetect(opts)` (combined wrapper — existing callers)

Composes `setupAuthContext` then `detectRenderAt`:

```javascript
async function renderReviewDetect(opts) {
  const { browser, requested_route, base_url, is_first_page = false } = opts;
  const setup = await setupAuthContext(browser, opts);
  const { context, authSource, fallbackReason, reviewMethodEarly } = setup;

  if (reviewMethodEarly) {
    // auth_requirement="required" + storageState failed
    return {
      review_method: "prereq-unmet",
      review_evidence: {
        requested_route,
        final_url: null,
        auth_source: authSource,
        fallback_reason: fallbackReason,
        content_density: null,
        expected_destination: opts.expected_destination || null,
        final_status: null,
        route_pattern: opts.route_pattern || null,
      },
      context,
      page: null,
    };
  }

  const detected = await detectRenderAt(context, opts);
  return { ...detected, context };
}
```

**Existing callers** (design-critic, accessibility-scanner) call
`renderReviewDetect({browser, requested_route, base_url, is_first_page})`
with no `expected_destination` / `auth_requirement` — their returned
shape is byte-identical to pre-change apart from the additive
`expected_destination: null` in `review_evidence`.

## Section 7 — Caller policy table

Each caller declares its `(auth_requirement, expected_destination,
review_method → verdict)` mapping here. New callers MUST add a row
before invoking this pattern.

| Caller | `auth_requirement` | `expected_destination` | Primitive | Verdict mapping |
|---|---|---|---|---|
| `design-critic` | `"optional"` (default) | unset (= `requested_route`) | `renderReviewDetect` (wrapper) | `source-only` / `unknown` → `"unresolved"` (enforced in state-3b) |
| `accessibility-scanner` | `"optional"` (default) | unset | `renderReviewDetect` (wrapper) | `source-only` / `unknown` → skip page, omit from `pages_scanned` |
| `ux-journeyer` | dynamic per journey (`"anonymous"` when starting on public route, `"required"` when starting on authed route, else `"optional"`) | `step.destination_route` per step | `setupAuthContext` once, then `classifyCurrentPage` per step after click | Defined in `.claude/agents/ux-journeyer.md` "Render Review Policy Table" |
| `behavior-verifier` | dynamic per behavior via `given-auth-matcher.md` | `behavior.entry_route` | `renderReviewDetect` (wrapper) per behavior | Defined in `.claude/agents/behavior-verifier.md` "Render Review Policy Table" |

The shared enforcement of these mappings lives in
`.claude/patterns/review-verdict-gate.md` and is invoked by each state
where the reviewer trace lands (see that file + `state-registry.json`).

## Caller contract

- The caller owns the dev server (start + port + cleanup) — this pattern
  never starts or stops a server.
- The caller decides what to do per `review_method`, per the policy table
  (Section 7). Examples:
  - `design-critic`: `source-only`/`unknown` → screenshot for evidence, skip
    Layers 1-3 review, emit `verdict="unresolved"` with `caveat = fallback_reason`.
  - `accessibility-scanner`: `source-only`/`unknown` → skip axe-core scan for
    the page, do NOT count it in `pages_scanned`, do NOT emit violations.
  - `ux-journeyer`: `prereq-unmet` → `verdict="blocked"`; `source-only` with
    auth-path final → step error; `source-only` with non-auth final → dead-end.
  - `behavior-verifier`: `prereq-unmet` → `verdict="SKIPPED"`; `source-only`
    with auth-path final → FAIL [B3]; `source-only` with non-auth final →
    DEGRADED.
- Set `is_first_page = true` only for the first **auth-gated** route per run
  (use a `firstAuthGatedSeen` flag — see `.claude/procedures/accessibility-scanner.md`
  Section 2 for the reference implementation). Do **not** use `i === 0` — that
  mis-fires the `demo-mode-bypass-failed` diagnostic on anonymous journeys
  and non-auth behaviors. The diagnostic is additionally suppressed by
  Section 3 when `auth_requirement="anonymous"`.

## Appendix — 4th reviewer worked example

This appendix makes the extrapolation claim concrete. Suppose a hypothetical
`security-attacker` reviewer is added to `/verify` — it navigates a list of
attack-surface routes (`/admin`, `/internal`, `/api/debug`) to confirm auth
gates are in place. What does plugging it into this pattern cost?

| Step | Change | Touches this pattern file? |
|---|---|---|
| 1. Decide `auth_requirement` | Attacker simulates a logged-in attacker → `"required"` (expects valid session and wants to verify that even WITH session, certain routes are gated out). | No |
| 2. Pick primitive | Attacker navigates many routes with `page.goto` → use `detectRenderAt` (wrapper or unit directly). | No |
| 3. Per-route verdict table | In `.claude/agents/security-attacker.md`: `rendered-*` on restricted route → FAIL (attack succeeded); `source-only` with `final ∈ AUTH_PATHS` → PASS (auth gate held); `source-only` with `final ∉ AUTH_PATHS` → DEGRADED (unexpected redirect); `prereq-unmet` → SKIPPED. Note the inverted semantic (PASS on auth-redirect). | No |
| 4. Trace extension | Add `| security-attacker | per_route_reviews | array | ... |` to `agent-trace-protocol.md` Extension Fields. | No |
| 5. Caller policy row | Add a new row to Section 7's Caller Policy Table (above). | **Yes — 1 row** |
| 6. Gate wiring | In the state that spawns `security-attacker`, invoke `review-verdict-gate.md` against its trace after agent returns. Add a matching assertion to the state's `state-registry.json` VERIFY entry. | No (external file) |

Total touches to this pattern file: **one new row in Section 7**. No
changes to Inputs, Outputs, Section 1/2/3/4/5/6, or Caller contract.

If a future reviewer needs a semantic that breaks this budget (e.g.,
classification by screenshot pixel-diff rather than URL), that is a
different detection mechanism and warrants a new pattern file — not an
extension of this one. The policy table in Section 7 is the canary: if a
new caller's row becomes unfillable, re-evaluate the split-vs-extend
decision at that point.
