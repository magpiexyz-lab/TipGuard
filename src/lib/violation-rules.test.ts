import { describe, expect, it } from "vitest";
import {
  checkOvertimeBasis,
  checkTipPoolEligibility,
  checkSubminimumShortfall,
  checkNoticeStatus,
} from "./violation-rules";

describe("checkOvertimeBasis", () => {
  it("violating: overtime premium computed off the reduced cash wage", () => {
    // Full minimum wage $7.25 -> required OT rate $10.875/hr. Employer paid
    // overtime at 1.5x the $2.13 cash wage ($3.195/hr) instead.
    const finding = checkOvertimeBasis({
      fullMinimumWage: 7.25,
      overtimeHours: 5,
      overtimeRateUsed: 2.13 * 1.5,
    });
    expect(finding).not.toBeNull();
    expect(finding?.ruleClass).toBe("overtime_base");
    expect(finding?.severity).toBe("critical");
    expect(finding?.estimatedExposureUsd).toBeGreaterThan(0);
  });

  it("compliant: overtime premium computed off the full minimum wage", () => {
    const finding = checkOvertimeBasis({
      fullMinimumWage: 7.25,
      overtimeHours: 5,
      overtimeRateUsed: 7.25 * 1.5,
    });
    expect(finding).toBeNull();
  });

  it("no finding when there are no overtime hours", () => {
    expect(checkOvertimeBasis({ fullMinimumWage: 7.25, overtimeHours: 0, overtimeRateUsed: 0 })).toBeNull();
  });
});

describe("checkTipPoolEligibility", () => {
  const eligibleRoles = ["server", "bartender", "busser"];

  it("violating: a manager shares in the tip pool", () => {
    const finding = checkTipPoolEligibility({
      employeeRole: "Manager",
      isInTipPool: true,
      eligibleRoles,
      weeklyTipPoolShareUsd: 150,
    });
    expect(finding).not.toBeNull();
    expect(finding?.ruleClass).toBe("ineligible_tip_pool");
    expect(finding?.severity).toBe("critical");
    expect(finding?.estimatedExposureUsd).toBe(150);
  });

  it("compliant: a server (eligible role) shares in the tip pool", () => {
    const finding = checkTipPoolEligibility({
      employeeRole: "Server",
      isInTipPool: true,
      eligibleRoles,
    });
    expect(finding).toBeNull();
  });

  it("no finding when the employee is not in the tip pool at all", () => {
    expect(
      checkTipPoolEligibility({ employeeRole: "Manager", isInTipPool: false, eligibleRoles })
    ).toBeNull();
  });
});

describe("checkSubminimumShortfall", () => {
  it("violating: cash wage plus tips falls below the applicable minimum wage", () => {
    const finding = checkSubminimumShortfall({
      cashWagePaid: 2.13,
      hoursWorked: 40,
      tipsReceived: 100, // far below the $5.12 credit x 40h needed to reach $7.25/hr
      applicableMinimumWage: 7.25,
    });
    expect(finding).not.toBeNull();
    expect(finding?.ruleClass).toBe("subminimum_shortfall");
    expect(finding?.severity).toBe("high");
    expect(finding?.estimatedExposureUsd).toBeGreaterThan(0);
  });

  it("compliant: cash wage plus tips meets or exceeds the applicable minimum wage", () => {
    const finding = checkSubminimumShortfall({
      cashWagePaid: 2.13,
      hoursWorked: 40,
      tipsReceived: 400, // (2.13*40 + 400) / 40 = 12.13/hr >= 7.25/hr
      applicableMinimumWage: 7.25,
    });
    expect(finding).toBeNull();
  });
});

describe("checkNoticeStatus", () => {
  const currentRuleVersion = "2026.1";

  it("violating: no notice exists for the employee", () => {
    const finding = checkNoticeStatus({ noticeExists: false, currentRuleVersion });
    expect(finding).not.toBeNull();
    expect(finding?.ruleClass).toBe("missing_notice");
    expect(finding?.severity).toBe("critical");
  });

  it("violating: notice exists but is not signed", () => {
    const finding = checkNoticeStatus({
      noticeExists: true,
      noticeStatus: "sent",
      noticeRuleVersion: currentRuleVersion,
      currentRuleVersion,
    });
    expect(finding).not.toBeNull();
    expect(finding?.ruleClass).toBe("missing_notice");
  });

  it("violating: signed notice is for a stale rule version", () => {
    const finding = checkNoticeStatus({
      noticeExists: true,
      noticeStatus: "signed",
      noticeRuleVersion: "2025.4",
      currentRuleVersion,
    });
    expect(finding).not.toBeNull();
    expect(finding?.ruleClass).toBe("missing_notice");
  });

  it("compliant: signed notice on the current rule version", () => {
    const finding = checkNoticeStatus({
      noticeExists: true,
      noticeStatus: "signed",
      noticeRuleVersion: currentRuleVersion,
      currentRuleVersion,
    });
    expect(finding).toBeNull();
  });
});
