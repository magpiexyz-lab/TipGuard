import { describe, expect, it } from "vitest";
import { parseRosterCsv } from "./roster-csv";

const HEADER = "name,email,role,hire_date,hourly_rate,state";

describe("parseRosterCsv", () => {
  it("imports all valid rows", () => {
    const csv = [
      HEADER,
      "Jane Doe,jane@bar.com,server,2024-01-15,2.13,TX",
      "John Smith,john@bar.com,bartender,2023-06-01,2.13,TX",
    ].join("\n");

    const result = parseRosterCsv(csv);
    expect(result.rowsTotal).toBe(2);
    expect(result.rowsImported).toBe(2);
    expect(result.rowsFailed).toBe(0);
    expect(result.errors).toHaveLength(0);
    expect(result.validRows[0]).toEqual({
      name: "Jane Doe",
      email: "jane@bar.com",
      role: "server",
      hireDate: "2024-01-15",
      hourlyRate: 2.13,
      state: "TX",
    });
  });

  it("collects invalid rows as errors and imports valid rows WITHOUT aborting the whole batch", () => {
    const csv = [
      HEADER,
      "Jane Doe,jane@bar.com,server,2024-01-15,2.13,TX", // valid
      "Bad Email,not-an-email,server,2024-01-15,2.13,TX", // invalid email
      "Missing Rate,mr@bar.com,server,2024-01-15,notanumber,TX", // malformed rate
      ",,,,,", // missing everything
      "Good Row,good@bar.com,busser,2024-02-01,5.00,FL", // valid
    ].join("\n");

    const result = parseRosterCsv(csv);
    expect(result.rowsTotal).toBe(5);
    expect(result.rowsImported).toBe(2);
    expect(result.rowsFailed).toBe(3);
    expect(result.validRows.map((r) => r.email)).toEqual(["jane@bar.com", "good@bar.com"]);
    expect(result.errors).toHaveLength(3);
    expect(result.errors[0].reason).toMatch(/invalid email/i);
    expect(result.errors[1].reason).toMatch(/hourly rate/i);
    expect(result.errors[2].reason).toMatch(/missing required field/i);
  });

  it("rejects an invalid state code without aborting other rows", () => {
    const csv = [HEADER, "Jane Doe,jane@bar.com,server,2024-01-15,2.13,Texas"].join("\n");
    const result = parseRosterCsv(csv);
    expect(result.rowsFailed).toBe(1);
    expect(result.errors[0].reason).toMatch(/invalid state code/i);
  });

  it("returns an empty result for an empty CSV", () => {
    const result = parseRosterCsv("");
    expect(result).toEqual({ validRows: [], errors: [], rowsTotal: 0, rowsImported: 0, rowsFailed: 0 });
  });
});
