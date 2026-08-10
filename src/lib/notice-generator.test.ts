import { describe, expect, it } from "vitest";
import { generateEmployeeNotice, COUNSEL_REVIEW_DISCLAIMER } from "./notice-generator";

describe("generateEmployeeNotice", () => {
  it("includes all five federally required notice elements for a tip-credit state", () => {
    const result = generateEmployeeNotice({
      employeeName: "Jane Doe",
      employerName: "The Brass Rail",
      state: "TX",
      cashWagePaid: 2.13,
    });

    if ("error" in result) throw new Error("expected a generated notice");
    expect(result.tipCreditClaimed).toBe(true);

    const requiredPhrases = [
      "cash wage the employer is paying",
      "additional amount claimed by the employer as a tip credit",
      "tip credit claimed cannot exceed the amount of tips actually received",
      "all tips received by the employee must be retained",
      "tip credit does not apply to any employee who has not been informed",
    ];
    for (const phrase of requiredPhrases) {
      expect(result.noticeText.toLowerCase()).toContain(phrase.toLowerCase());
    }
  });

  it("attaches the counsel-review disclaimer and rule-version stamp on every notice", () => {
    const result = generateEmployeeNotice({
      employeeName: "Jane Doe",
      employerName: "The Brass Rail",
      state: "TX",
      cashWagePaid: 2.13,
    });
    if ("error" in result) throw new Error("expected a generated notice");
    expect(result.disclaimer).toBe(COUNSEL_REVIEW_DISCLAIMER);
    expect(result.noticeText).toContain(COUNSEL_REVIEW_DISCLAIMER);
    expect(result.ruleVersion).toBeTruthy();
    expect(result.noticeText).toContain(result.ruleVersion);
  });

  it("renders a no-tip-credit notice (tipCreditClaimed: false) for a state that eliminated the credit, still with the disclaimer", () => {
    const result = generateEmployeeNotice({
      employeeName: "John Smith",
      employerName: "Coastal Bistro",
      state: "CA",
      cashWagePaid: 16.5,
    });
    if ("error" in result) throw new Error("expected a generated notice");
    expect(result.tipCreditClaimed).toBe(false);
    expect(result.maxTipCredit).toBe(0);
    expect(result.noticeText).toContain("does not permit a tip credit");
    expect(result.noticeText).toContain(COUNSEL_REVIEW_DISCLAIMER);
  });

  it("returns an explicit unsupported_state error for an unmapped state — never fabricates a notice", () => {
    const result = generateEmployeeNotice({
      employeeName: "Jane Doe",
      employerName: "The Brass Rail",
      state: "ZZ",
      cashWagePaid: 2.13,
    });
    expect("error" in result).toBe(true);
    if (!("error" in result)) throw new Error("expected an unsupported_state error");
    expect(result.error).toBe("unsupported_state");
    expect(result.state).toBe("ZZ");
  });
});
