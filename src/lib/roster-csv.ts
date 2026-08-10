// Roster CSV parse/validate (b-04).
//
// Pure function, no network. Valid rows are collected for import; invalid
// rows are collected as errors and the whole import is NEVER aborted because
// of them — the caller imports `validRows` and reports `errors` inline.

export interface RosterRowValid {
  name: string;
  email: string;
  role: string;
  /** ISO date (YYYY-MM-DD). */
  hireDate: string;
  hourlyRate: number;
  /** Two-letter US state code. */
  state: string;
}

export interface RosterRowError {
  /** 1-based row number within the data rows (excludes the header row). */
  row: number;
  reason: string;
  raw: Record<string, string>;
}

export interface RosterParseResult {
  validRows: RosterRowValid[];
  errors: RosterRowError[];
  rowsTotal: number;
  rowsImported: number;
  rowsFailed: number;
}

const REQUIRED_COLUMNS = ["name", "email", "role", "hire_date", "hourly_rate", "state"] as const;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const STATE_RE = /^[A-Za-z]{2}$/;

export function parseRosterCsv(csvText: string): RosterParseResult {
  const lines = csvText.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length === 0) {
    return { validRows: [], errors: [], rowsTotal: 0, rowsImported: 0, rowsFailed: 0 };
  }

  const header = lines[0].split(",").map((h) => h.trim().toLowerCase());
  const dataLines = lines.slice(1);

  const validRows: RosterRowValid[] = [];
  const errors: RosterRowError[] = [];

  dataLines.forEach((line, idx) => {
    const cells = line.split(",").map((c) => c.trim());
    const raw: Record<string, string> = {};
    header.forEach((col, i) => {
      raw[col] = cells[i] ?? "";
    });

    const rowNumber = idx + 1;

    const missing = REQUIRED_COLUMNS.filter((c) => !raw[c]);
    if (missing.length > 0) {
      errors.push({ row: rowNumber, reason: `Missing required field(s): ${missing.join(", ")}`, raw });
      return;
    }

    if (!EMAIL_RE.test(raw.email)) {
      errors.push({ row: rowNumber, reason: `Invalid email: ${raw.email}`, raw });
      return;
    }

    if (!STATE_RE.test(raw.state)) {
      errors.push({ row: rowNumber, reason: `Invalid state code: ${raw.state}`, raw });
      return;
    }

    const rate = Number(raw.hourly_rate);
    if (!Number.isFinite(rate) || rate <= 0) {
      errors.push({ row: rowNumber, reason: `Malformed hourly rate: ${raw.hourly_rate}`, raw });
      return;
    }

    const hireDate = new Date(raw.hire_date);
    if (Number.isNaN(hireDate.getTime())) {
      errors.push({ row: rowNumber, reason: `Malformed hire date: ${raw.hire_date}`, raw });
      return;
    }

    validRows.push({
      name: raw.name,
      email: raw.email.toLowerCase(),
      role: raw.role,
      hireDate: hireDate.toISOString().slice(0, 10),
      hourlyRate: rate,
      state: raw.state.toUpperCase(),
    });
  });

  return {
    validRows,
    errors,
    rowsTotal: dataLines.length,
    rowsImported: validRows.length,
    rowsFailed: errors.length,
  };
}
