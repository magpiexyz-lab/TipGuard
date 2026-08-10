import { describe, expect, it } from "vitest";
import { scoreAuditReadiness, type ScoringInput } from "./scoring";

const BASE_INPUT: ScoringInput = {
  state: "TX",
  claimsTipCredit: true,
  noticeCoverage: "all",
  tipPoolIncludesIneligibleWorkers: false,
  overtimeBasis: "full_minimum_wage",
  newHireProcess: "consistent",
  staffCount: 20,
};

describe("scoreAuditReadiness", () => {
  it("returns the top score extreme (100) when every gap rule is clean", () => {
    const result = scoreAuditReadiness(BASE_INPUT);
    expect(result.score).toBe(100);
    expect(result.gaps).toHaveLength(0);
    expect(result.estimatedExposureUsd).toEqual({ low: 0, high: 0 });
  });

  it("returns 100 when the restaurant does not claim the tip credit, regardless of other answers", () => {
    const result = scoreAuditReadiness({
      ...BASE_INPUT,
      claimsTipCredit: false,
      noticeCoverage: "none",
      tipPoolIncludesIneligibleWorkers: true,
      overtimeBasis: "cash_wage",
      newHireProcess: "none",
    });
    expect(result.score).toBe(100);
    expect(result.gaps).toHaveLength(0);
  });

  it("returns the bottom score extreme (0) when every gap rule fires", () => {
    const result = scoreAuditReadiness({
      ...BASE_INPUT,
      noticeCoverage: "none",
      tipPoolIncludesIneligibleWorkers: true,
      overtimeBasis: "cash_wage",
      newHireProcess: "none",
    });
    expect(result.score).toBe(0);
    expect(result.gaps).toHaveLength(4);
    expect(result.estimatedExposureUsd.low).toBeGreaterThan(0);
    expect(result.estimatedExposureUsd.high).toBeGreaterThan(result.estimatedExposureUsd.low);
  });

  it("gap rule: missing_signed_notices — 'none' coverage deducts more than 'some'", () => {
    const none = scoreAuditReadiness({ ...BASE_INPUT, noticeCoverage: "none" });
    const some = scoreAuditReadiness({ ...BASE_INPUT, noticeCoverage: "some" });
    expect(none.gaps[0].id).toBe("missing_signed_notices");
    expect(some.gaps[0].id).toBe("missing_signed_notices");
    expect(none.gaps[0].pointsDeducted).toBeGreaterThan(some.gaps[0].pointsDeducted);
    expect(none.score).toBeLessThan(some.score);
  });

  it("gap rule: ineligible_tip_pool fires only when a manager/BOH worker shares the pool", () => {
    const result = scoreAuditReadiness({ ...BASE_INPUT, tipPoolIncludesIneligibleWorkers: true });
    expect(result.gaps.map((g) => g.id)).toContain("ineligible_tip_pool");
    const clean = scoreAuditReadiness(BASE_INPUT);
    expect(clean.gaps.map((g) => g.id)).not.toContain("ineligible_tip_pool");
  });

  it("gap rule: overtime_on_subminimum fires only when overtime is based on the cash wage", () => {
    const result = scoreAuditReadiness({ ...BASE_INPUT, overtimeBasis: "cash_wage" });
    expect(result.gaps.map((g) => g.id)).toContain("overtime_on_subminimum");
    const clean = scoreAuditReadiness(BASE_INPUT);
    expect(clean.gaps.map((g) => g.id)).not.toContain("overtime_on_subminimum");
  });

  it("gap rule: inconsistent_new_hire_process — 'none' is worse than 'inconsistent'", () => {
    const none = scoreAuditReadiness({ ...BASE_INPUT, newHireProcess: "none" });
    const inconsistent = scoreAuditReadiness({ ...BASE_INPUT, newHireProcess: "inconsistent" });
    expect(none.gaps[0].severity).toBe("high");
    expect(inconsistent.gaps[0].severity).toBe("medium");
    expect(none.gaps[0].pointsDeducted).toBeGreaterThan(inconsistent.gaps[0].pointsDeducted);
  });

  it("ranks gaps by pointsDeducted descending", () => {
    const result = scoreAuditReadiness({
      ...BASE_INPUT,
      noticeCoverage: "some", // 20
      tipPoolIncludesIneligibleWorkers: true, // 25
      newHireProcess: "inconsistent", // 8
    });
    const points = result.gaps.map((g) => g.pointsDeducted);
    expect(points).toEqual([...points].sort((a, b) => b - a));
  });

  it("scales exposure with staff count", () => {
    const small = scoreAuditReadiness({ ...BASE_INPUT, noticeCoverage: "none", staffCount: 5 });
    const large = scoreAuditReadiness({ ...BASE_INPUT, noticeCoverage: "none", staffCount: 50 });
    expect(large.estimatedExposureUsd.high).toBeGreaterThan(small.estimatedExposureUsd.high);
  });
});
