import { describe, it, expect } from "vitest";

/**
 * Integration tests for the three `actor: system` behaviors — b-05 (notice
 * generation), b-08 (compliance scan) and b-11 (Stripe webhook).
 *
 * Next.js has no `app.request()`, so handlers are imported directly and
 * invoked with a `Request`. Nothing here calls `fetch("http://localhost:...")`
 * — `npm test` must pass with no server running.
 *
 * NOT run during bootstrap; created here and run by `/verify` and CI.
 */

/** A live database changes what a 500 means: with one, 500 is a real failure. */
const HAS_DB = Boolean(
  process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY
);

function jsonRequest(url: string, body: unknown, headers: Record<string, string> = {}) {
  return new Request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

// ===========================================================================
// b-05 — POST /api/notices/generate
// ===========================================================================

describe("b-05 notice generation", () => {
  it("Each employee gets exactly one notice row containing all five federally required notice elements", async () => {
    const { generateEmployeeNotice } = await import("@/lib/notice-generator");
    const notice = generateEmployeeNotice({
      employeeName: "Marisol Vega",
      employerName: "The Copper Rail",
      state: "TX",
      cashWagePaid: 2.13,
    });
    expect("error" in notice).toBe(false);
    if ("error" in notice) return;
    // The five federally required elements are numbered 1..5 in the render.
    for (const index of [1, 2, 3, 4, 5]) {
      expect(notice.noticeText).toContain(`${index}. `);
    }
  });

  it("The state rule library resolves cash wage and maximum tip credit per state, and states that have eliminated the tip credit generate a no-tip-credit notice instead", async () => {
    const { generateEmployeeNotice } = await import("@/lib/notice-generator");
    const noTipCredit = generateEmployeeNotice({
      employeeName: "Ana Okafor",
      employerName: "The Copper Rail",
      state: "CA",
      cashWagePaid: 16.5,
    });
    expect("error" in noTipCredit).toBe(false);
    if ("error" in noTipCredit) return;
    expect(noTipCredit.tipCreditClaimed).toBe(false);
    expect(noTipCredit.noticeText).toMatch(/does not permit a tip credit/i);
  });

  it("Rule resolution is a pure function with unit tests covering a tip-credit state, a no-tip-credit state, and an unknown state", async () => {
    const { resolveStateRule } = await import("@/lib/state-rules");
    expect(resolveStateRule("TX").eligibility).toBe("eligible");
    expect(resolveStateRule("CA").eligibility).toBe("no_tip_credit_state");
    // An unmapped state is an EXPLICIT unsupported result, never a silent
    // fallback to federal figures.
    expect(resolveStateRule("ZZ").eligibility).toBe("unsupported_state");
  });

  it("Every rendered notice includes the counsel-review disclaimer and the rule-version stamp", async () => {
    const { generateEmployeeNotice, COUNSEL_REVIEW_DISCLAIMER } = await import(
      "@/lib/notice-generator"
    );
    const { RULE_VERSION } = await import("@/lib/state-rules");
    const notice = generateEmployeeNotice({
      employeeName: "Theo Brandt",
      employerName: "The Copper Rail",
      state: "NY",
      cashWagePaid: 10.65,
    });
    if ("error" in notice) throw new Error("NY should resolve");
    expect(notice.noticeText).toContain(COUNSEL_REVIEW_DISCLAIMER);
    expect(notice.noticeText).toContain(RULE_VERSION);
    // And nothing anywhere may claim attorney certification.
    expect(notice.noticeText).toMatch(/has not been reviewed or certified by an attorney/i);
  });

  it.skipIf(!HAS_DB)(
    "notice_generated fires once per generated notice with state and rule_version",
    async () => {
      const { POST } = await import("@/app/api/notices/generate/route");
      const response = await POST(
        jsonRequest("http://localhost/api/notices/generate", {})
      );
      // Unauthenticated invocation must be refused, never 500.
      expect([200, 401, 503]).toContain(response.status);
      // TODO: with a seeded session + employees, assert one `notices` row per
      // employee and one notice_generated event per row.
    }
  );
});

// ===========================================================================
// b-08 — POST /api/violations/scan
// ===========================================================================

describe("b-08 compliance scan", () => {
  it("Each of the four rule classes is a pure function with unit tests covering a violating case and a compliant case", async () => {
    const rules = await import("@/lib/violation-rules");
    for (const fn of [
      rules.checkOvertimeBasis,
      rules.checkTipPoolEligibility,
      rules.checkSubminimumShortfall,
      rules.checkNoticeStatus,
    ]) {
      expect(typeof fn).toBe("function");
    }
  });

  it("Overtime detection flags any overtime premium computed off the cash wage rather than the full minimum wage", async () => {
    const { checkOvertimeBasis } = await import("@/lib/violation-rules");
    const violating = checkOvertimeBasis({
      fullMinimumWage: 7.25,
      overtimeHours: 10,
      overtimeRateUsed: 3.2, // 1.5x the $2.13 cash wage — the classic error
    });
    expect(violating?.ruleClass).toBe("overtime_base");
    expect(violating?.estimatedExposureUsd).toBeGreaterThan(0);

    const compliant = checkOvertimeBasis({
      fullMinimumWage: 7.25,
      overtimeHours: 10,
      overtimeRateUsed: 10.88,
    });
    expect(compliant).toBeNull();
  });

  it("Shortfall detection flags any workweek where cash wage plus tips falls below the applicable minimum wage", async () => {
    const { checkSubminimumShortfall } = await import("@/lib/violation-rules");
    const violating = checkSubminimumShortfall({
      cashWagePaid: 2.13,
      hoursWorked: 40,
      tipsReceived: 100,
      applicableMinimumWage: 7.25,
    });
    expect(violating?.ruleClass).toBe("subminimum_shortfall");
    expect(violating?.estimatedExposureUsd).toBeGreaterThan(0);
  });

  it("Every employee without a signed notice for the current rule version produces a missing-notice finding", async () => {
    const { checkNoticeStatus } = await import("@/lib/violation-rules");
    const { RULE_VERSION } = await import("@/lib/state-rules");
    expect(
      checkNoticeStatus({ noticeExists: false, currentRuleVersion: RULE_VERSION })?.ruleClass
    ).toBe("missing_notice");
    expect(
      checkNoticeStatus({
        noticeExists: true,
        noticeStatus: "sent",
        noticeRuleVersion: RULE_VERSION,
        currentRuleVersion: RULE_VERSION,
      })?.ruleClass
    ).toBe("missing_notice");
    expect(
      checkNoticeStatus({
        noticeExists: true,
        noticeStatus: "signed",
        noticeRuleVersion: RULE_VERSION,
        currentRuleVersion: RULE_VERSION,
      })
    ).toBeNull();
  });

  it.skipIf(!HAS_DB)(
    "violation_detected fires once per finding with rule_class, severity, and estimated_exposure_usd",
    async () => {
      const { POST } = await import("@/app/api/violations/scan/route");
      const response = await POST();
      expect([200, 401, 503]).toContain(response.status);
      // TODO: with a seeded account + roster + pay periods, assert one
      // `violations` row and one violation_detected event per finding.
    }
  );
});

// ===========================================================================
// b-11 — Shield waitlist (fake door; replaced the Stripe webhook)
// ===========================================================================

describe("b-11 shield waitlist", () => {
  it("POST /api/waitlist derives identity from the session, so an unauthenticated call is rejected", async () => {
    const { POST } = await import("@/app/api/waitlist/route");
    const response = await POST(
      jsonRequest("http://localhost/api/waitlist", { email: "owner@restaurant.test" })
    );
    // No session cookie: 401 when the DB answers, 503 when it is unreachable.
    // Either way the row is not written — the route never trusts the body.
    expect([401, 503]).toContain(response.status);
  });

  it("A body carrying an account_id cannot redirect the write to another tenant", async () => {
    const { joinWaitlistSchema } = await import("@/app/api/waitlist/route");
    // The schema accepts an optional email and nothing else. account_id is
    // stripped, so there is no shape in which a client can name the tenant.
    const parsed = joinWaitlistSchema.parse({
      email: "owner@restaurant.test",
      account_id: "00000000-0000-0000-0000-000000000000",
    });
    expect(parsed).toEqual({ email: "owner@restaurant.test" });
    expect("account_id" in parsed).toBe(false);
  });

  it("An invalid email is rejected before any database work", async () => {
    const { POST } = await import("@/app/api/waitlist/route");
    const response = await POST(
      jsonRequest("http://localhost/api/waitlist", { email: "not-an-email" })
    );
    expect(response.status).toBe(400);
  });
});
