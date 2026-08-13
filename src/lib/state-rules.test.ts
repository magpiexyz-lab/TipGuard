import { describe, expect, it } from "vitest";
import { resolveStateRule, isStateSupported, RULE_VERSION } from "./state-rules";

describe("resolveStateRule", () => {
  it("resolves a tip-credit state (TX) with cash wage floor, max tip credit, and notice elements", () => {
    const result = resolveStateRule("TX");
    expect(result.eligibility).toBe("eligible");
    if (result.eligibility !== "eligible") throw new Error("expected eligible");
    expect(result.state).toBe("TX");
    expect(result.ruleVersion).toBe(RULE_VERSION);
    expect(result.cashWageFloor).toBeLessThan(result.standardMinimumWage);
    expect(result.maxTipCredit).toBeCloseTo(result.standardMinimumWage - result.cashWageFloor, 5);
    expect(result.requiredNoticeElements).toHaveLength(5);
    expect(result.tipPoolEligibleRoles).toContain("server");
    expect(result.tipPoolEligibleRoles).not.toContain("manager");
  });

  it("resolves a state that has eliminated the tip credit (CA) with maxTipCredit 0", () => {
    const result = resolveStateRule("CA");
    expect(result.eligibility).toBe("no_tip_credit_state");
    if (result.eligibility !== "no_tip_credit_state") throw new Error("expected no_tip_credit_state");
    expect(result.maxTipCredit).toBe(0);
    expect(result.cashWageFloor).toBe(result.standardMinimumWage);
    // Even no-tip-credit states still carry notice elements — a restaurant
    // that mistakenly claims a credit there still needs the education notice.
    expect(result.requiredNoticeElements).toHaveLength(5);
  });

  it("resolves an unknown state to an explicit unsupported result — never a silent federal fallback", () => {
    const result = resolveStateRule("zz");
    expect(result.eligibility).toBe("unsupported_state");
    expect(result.state).toBe("ZZ");
    // The unsupported branch must NOT carry any rule figures at all.
    expect((result as unknown as Record<string, unknown>).cashWageFloor).toBeUndefined();
    expect((result as unknown as Record<string, unknown>).maxTipCredit).toBeUndefined();
  });

  it("normalizes state code casing and whitespace", () => {
    expect(resolveStateRule(" tx ").eligibility).toBe("eligible");
  });

  it("isStateSupported reflects the same resolution", () => {
    expect(isStateSupported("TX")).toBe(true);
    expect(isStateSupported("CA")).toBe(true);
    expect(isStateSupported("ZZ")).toBe(false);
  });
});
