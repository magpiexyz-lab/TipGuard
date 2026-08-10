import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { createServerSupabaseClient } from "@/lib/supabase-server";
import type { EmployeeRow, ViolationRow } from "@/lib/types";

import {
  buildSampleFindings,
  byExposureDesc,
  toFindingView,
  usesDemoData,
  type FindingView,
} from "./findings";
import { ViolationsClient } from "./violations-client";

// The loader reads the session cookie and redirects when it is absent — the
// route must never be captured as a static prerender.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Open findings — TipGuard",
  description:
    "Every open tip-credit finding against your restaurant, ranked by estimated back-pay exposure, with the plain-English explanation and the fix that closes it.",
};

/** b-09: the violations page is a read of the scan output, never a re-detection. */
export default async function ViolationsPage() {
  // eslint-disable-next-line react-hooks/purity -- Server Component: purity rule does not apply
  const now = Date.now();

  if (usesDemoData()) {
    const findings = buildSampleFindings(now).sort(byExposureDesc);
    return <ViolationsClient initialFindings={findings} hasEverScanned />;
  }

  const supabase = await createServerSupabaseClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  // `last_scan_at` — not `violations.length > 0` — is what distinguishes
  // "never scanned" from "scanned and came back genuinely clean". Inferring it
  // from the finding count told an account with a clean first scan to "run
  // your first scan", which is both wrong and alarming.
  const { data: account } = await supabase
    .from("accounts")
    .select("id, last_scan_at")
    .eq("user_id", user.id)
    .single();

  if (!account) {
    // Authenticated but the account row has not been provisioned yet — there is
    // nothing to have scanned, so show the pre-scan state rather than an error.
    return <ViolationsClient initialFindings={[]} hasEverScanned={false} />;
  }

  const { id: accountId, last_scan_at: lastScanAt } = account as {
    id: string;
    last_scan_at: string | null;
  };

  // Ordering is applied by the database (b-09: ranked by estimated exposure) and
  // re-applied client-side so the order survives an optimistic status flip.
  const [violationsResult, employeesResult] = await Promise.all([
    supabase
      .from("violations")
      .select("*")
      .eq("account_id", accountId)
      .order("estimated_exposure_usd", { ascending: false }),
    supabase.from("employees").select("id,name,role").eq("account_id", accountId),
  ]);

  const violations = (violationsResult.data ?? []) as ViolationRow[];
  const employees = (employeesResult.data ?? []) as Pick<
    EmployeeRow,
    "id" | "name" | "role"
  >[];
  const employeeById = new Map(employees.map((employee) => [employee.id, employee]));

  const findings: FindingView[] = violations
    .map((row) =>
      toFindingView(row, row.employee_id ? employeeById.get(row.employee_id) ?? null : null, now)
    )
    .sort(byExposureDesc);

  return (
    <ViolationsClient initialFindings={findings} hasEverScanned={Boolean(lastScanAt)} />
  );
}
