import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { redirect } from "next/navigation";
import { ArrowRight, FileSignature, ShieldCheck, TriangleAlert, UserPlus } from "lucide-react";

import { BlurFade } from "@/components/magicui/blur-fade";
import { MagicEffects } from "@/components/magicui/effects";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { createServerSupabaseClient } from "@/lib/supabase-server";
import type { GapFinding } from "@/lib/scoring";
import { RULE_VERSION } from "@/lib/state-rules";
import type { AccountRow, EmployeeRow, NoticeRow, PlanTier, ViolationRow } from "@/lib/types";
import { cn } from "@/lib/utils";

import {
  buildSampleFindings,
  byExposureDesc,
  exposureLabel,
  formatUsd,
  RULE_CLASS_META,
  SEVERITY_META,
  toFindingView,
  totalExposure,
  usesDemoData,
  type FindingView,
} from "../violations/findings";
import { ReadinessDial } from "./readiness-dial";
import { UpgradeCta } from "./upgrade-cta";

// The loader reads the session cookie and redirects when it is absent — the
// route must never be captured as a static prerender.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Compliance dashboard — TipGuard",
  description:
    "Your current audit-readiness score, signed notice count, and open tip-credit findings in one view.",
};

/**
 * One severity ramp for the whole page — the carried-gap ledger and the open
 * finding cards read the same colour for the same weight, so the eye can rank
 * exposure by rule colour alone. Ember for critical, brass for high, muted for
 * medium; never a red/green traffic light.
 */
const SEVERITY_ACCENT: Record<
  GapFinding["severity"],
  { rule: string; bar: string; chip: string; figure: string }
> = {
  critical: {
    rule: "border-l-destructive/70",
    bar: "bg-destructive/80",
    chip: "bg-destructive/10 text-destructive",
    figure: "text-destructive",
  },
  high: {
    rule: "border-l-primary/70",
    bar: "bg-primary",
    chip: "bg-primary/15 text-brass-deep dark:text-primary",
    figure: "text-brass-deep dark:text-primary",
  },
  medium: {
    rule: "border-l-border",
    bar: "bg-border",
    chip: "bg-muted text-muted-foreground",
    figure: "text-muted-foreground",
  },
};

// --- Shapes assembled by the loader (local view models, not API contracts) ---

interface NoticeTally {
  total: number;
  sent: number;
  signed: number;
}

interface DashboardData {
  restaurantName: string;
  homeState: string;
  plan: PlanTier;
  readinessScore: number | null;
  gaps: GapFinding[];
  employeeCount: number;
  notices: NoticeTally;
  findings: FindingView[];
  /** Pre-fills the Shield waitlist panel (b-11). */
  email: string | null;
}

/** The questionnaire snapshot is stored as JSON — narrow it before rendering. */
function readGapList(raw: unknown): GapFinding[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((entry): entry is GapFinding => {
    if (typeof entry !== "object" || entry === null) return false;
    const candidate = entry as Partial<GapFinding>;
    return typeof candidate.label === "string" && typeof candidate.severity === "string";
  });
}

function tallyNotices(notices: Pick<NoticeRow, "status">[]): NoticeTally {
  return {
    total: notices.length,
    // "sent" counts every notice that has left the building — a signed notice
    // was necessarily sent first, so it stays in the numerator.
    sent: notices.filter((n) => n.status === "sent" || n.status === "signed").length,
    signed: notices.filter((n) => n.status === "signed").length,
  };
}

// --- Demo fixture (no Supabase project wired up) -----------------------------

function demoDashboard(now: number): DashboardData {
  return {
    restaurantName: "Ember & Rail",
    homeState: "TX",
    plan: "free",
    email: "owner@emberandrail.test",
    readinessScore: 47,
    gaps: [
      {
        id: "missing_signed_notices",
        label:
          "One or more tipped employees do not have a signed tip-credit notice on file",
        severity: "critical",
        pointsDeducted: 20,
      },
      {
        id: "overtime_on_subminimum",
        label:
          "Overtime is calculated off the $2.13 cash wage instead of the full minimum wage",
        severity: "critical",
        pointsDeducted: 20,
      },
      {
        id: "inconsistent_new_hire_process",
        label:
          "New hires are not consistently given a tip-credit notice before their first shift",
        severity: "medium",
        pointsDeducted: 8,
      },
    ],
    employeeCount: 14,
    notices: { total: 14, sent: 9, signed: 6 },
    findings: buildSampleFindings(now)
      .filter((finding) => finding.status === "open")
      .sort(byExposureDesc),
  };
}

// --- Loader ------------------------------------------------------------------

async function loadDashboard(now: number): Promise<DashboardData> {
  if (usesDemoData()) return demoDashboard(now);

  const supabase = await createServerSupabaseClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  const { data: accountRow } = await supabase
    .from("accounts")
    .select("*")
    .eq("user_id", user.id)
    .single();

  const account = (accountRow ?? null) as AccountRow | null;

  const empty: DashboardData = {
    restaurantName: account?.restaurant_name || "Your restaurant",
    homeState: account?.home_state || "—",
    plan: account?.plan ?? "free",
    readinessScore: account?.readiness_score ?? null,
    gaps: readGapList(account?.gap_list),
    employeeCount: 0,
    notices: { total: 0, sent: 0, signed: 0 },
    findings: [],
    email: user.email ?? null,
  };

  // Account row not provisioned yet (signup callback still in flight): render
  // the shell rather than erroring — the score attaches on the next load.
  if (!account) return empty;

  const [employeesResult, noticesResult, violationsResult] = await Promise.all([
    supabase.from("employees").select("id,name,role").eq("account_id", account.id),
    supabase.from("notices").select("status").eq("account_id", account.id),
    supabase
      .from("violations")
      .select("*")
      .eq("account_id", account.id)
      .eq("status", "open")
      .order("estimated_exposure_usd", { ascending: false }),
  ]);

  const employees = (employeesResult.data ?? []) as Pick<
    EmployeeRow,
    "id" | "name" | "role"
  >[];
  const employeeById = new Map(employees.map((employee) => [employee.id, employee]));
  const violations = (violationsResult.data ?? []) as ViolationRow[];

  return {
    ...empty,
    employeeCount: employees.length,
    notices: tallyNotices((noticesResult.data ?? []) as Pick<NoticeRow, "status">[]),
    findings: violations
      .map((row) =>
        toFindingView(
          row,
          row.employee_id ? employeeById.get(row.employee_id) ?? null : null,
          now
        )
      )
      .sort(byExposureDesc),
  };
}

/**
 * b-03 / b-09 / b-10 / b-14 — the post-signup home.
 *
 * `retain_return` is NOT fired here: it belongs to `<RetainTracker />`, which
 * scaffold-wire mounts once in the root layout so the return window is measured
 * globally rather than per page.
 */
export default async function DashboardPage() {
  // eslint-disable-next-line react-hooks/purity -- Server Component: purity rule does not apply
  const now = Date.now();
  const data = await loadDashboard(now);

  const openExposure = totalExposure(data.findings);
  const topFindings = data.findings.slice(0, 3);
  const hasRoster = data.employeeCount > 0;
  const outstandingNotices = Math.max(0, data.notices.total - data.notices.signed);

  // Contextual forward action: whatever most advances the file right now.
  const nextStep = !hasRoster
    ? { href: "/staff", label: "Import my staff roster" }
    : data.notices.sent === 0
      ? { href: "/notices", label: "Send notices for signature" }
      : data.findings.length > 0
        ? { href: "/violations", label: "Work my open findings" }
        : { href: "/audit-file", label: "Build my audit file" };

  return (
    <div className="min-h-screen">
      <MagicEffects />

      {/* ---------- Authority band ---------- */}
      <div className="dark surface-ink texture-grain bloom-brass border-b border-border">
        <div className="mx-auto max-w-[1180px] px-5 py-10 md:px-8 md:py-14">
          <div className="flex flex-wrap items-center gap-3">
            <p className="eyebrow">Compliance file &middot; {data.homeState}</p>
            <Badge
              className={cn(
                "rounded-sm font-mono text-[11px] tracking-[0.1em] uppercase",
                data.plan === "shield"
                  ? "bg-seal/20 text-seal-soft"
                  : "bg-muted text-muted-foreground"
              )}
            >
              {data.plan === "shield" ? "Shield" : "Free"}
            </Badge>
          </div>

          <div className="mt-4 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <h1 className="font-display text-4xl leading-[1.04] tracking-[-2px] md:text-[56px]">
                {data.restaurantName}
              </h1>
              <p className="mt-5 text-lg leading-[1.55] text-muted-foreground">
                Where your tip-credit file stands today, measured against the{" "}
                <span className="figure">{data.homeState}</span> rule set, version{" "}
                <span className="figure">{RULE_VERSION}</span>.
              </p>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <Link
                href={nextStep.href}
                className={cn(buttonVariants(), "h-11 rounded-full px-6 text-base")}
              >
                {nextStep.label}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1180px] px-5 py-8 md:px-8 md:py-10">
        {/* ---------- Where you stand ---------- */}
        <section aria-labelledby="standing-heading">
          <h2
            id="standing-heading"
            className="font-display text-2xl tracking-[-1.6px] md:text-[32px]"
          >
            Where you stand
          </h2>

          <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,340px)_1fr]">
            <ReadinessDial score={data.readinessScore} gapCount={data.gaps.length} />

            <dl className="grid gap-4 sm:grid-cols-2">
              <StatCard
                index={0}
                label="Signed notices"
                value={`${data.notices.signed}`}
                sub={
                  data.notices.total > 0
                    ? `of ${data.notices.total} generated · ${outstandingNotices} still outstanding`
                    : "No notices generated yet"
                }
                accent="text-chart-4"
              />
              <StatCard
                index={1}
                label="Notices sent"
                value={`${data.notices.sent}`}
                sub={
                  data.notices.sent > 0
                    ? "Awaiting employee signature where unsigned"
                    : "Nothing has gone out for signature yet"
                }
                accent="text-chart-2"
              />
              <StatCard
                index={2}
                label="Open findings"
                value={`${data.findings.length}`}
                sub={
                  data.findings.length > 0
                    ? "Ranked by estimated exposure on /violations"
                    : "Nothing flagged in the last scan"
                }
                accent={data.findings.length > 0 ? "text-chart-1" : "text-chart-4"}
              />
              <StatCard
                index={3}
                label="Estimated exposure"
                value={formatUsd(openExposure)}
                sub={
                  hasRoster
                    ? `Across ${data.employeeCount} tipped staff on file`
                    : "No roster imported yet"
                }
                accent={openExposure > 0 ? "text-chart-1" : "text-chart-4"}
              />
            </dl>
          </div>
        </section>

        {/* ---------- Gaps carried from the free score (b-03) ---------- */}
        {data.gaps.length > 0 ? (
          <section aria-labelledby="gaps-heading" className="mt-10">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <h2
                  id="gaps-heading"
                  className="font-display text-2xl tracking-[-1.6px] md:text-[32px]"
                >
                  Gaps from your readiness score
                </h2>
                <p className="mt-2 text-sm text-muted-foreground">
                  Carried over from the questionnaire you answered before signing up.
                </p>
              </div>
              <Link
                href="/notices"
                className={cn(
                  buttonVariants({ variant: "outline" }),
                  "h-11 px-5 text-base"
                )}
              >
                Close these gaps
              </Link>
            </div>

            {/* Ledger, not a bare list: a titled deduction column turns the
                right-hand void into a scannable figure stack. */}
            <div className="mt-5 overflow-hidden rounded-lg bg-card elev-1">
              <div className="texture-rule flex items-center justify-between gap-4 border-b border-border px-5 py-2.5">
                <p className="eyebrow">Carried gap</p>
                <p className="eyebrow">Deducted</p>
              </div>
              <ol>
                {data.gaps.map((gap, index) => {
                  const accent = SEVERITY_ACCENT[gap.severity];
                  return (
                    <li
                      key={`${gap.id}-${index}`}
                      className={cn(
                        "grid min-h-14 items-center gap-x-6 gap-y-3 border-t border-border/70 border-l-[3px] py-4 pr-5 pl-[17px] first:border-t-0 sm:grid-cols-[minmax(0,1fr)_auto]",
                        accent.rule
                      )}
                    >
                      <span className="flex items-start gap-3">
                        <span
                          aria-hidden="true"
                          className={cn(
                            "mt-px flex size-6 shrink-0 items-center justify-center rounded-sm",
                            accent.chip
                          )}
                        >
                          <TriangleAlert className="size-3.5" />
                        </span>
                        <span className="max-w-[54ch] text-[15px] leading-[1.5]">
                          {gap.label}
                        </span>
                      </span>
                      <span className="flex items-baseline gap-1.5 pl-9 sm:justify-end sm:pl-0">
                        <span
                          className={cn(
                            "figure text-2xl leading-none md:text-[28px]",
                            accent.figure
                          )}
                        >
                          &minus;{gap.pointsDeducted}
                        </span>
                        <span className="eyebrow">pts</span>
                      </span>
                    </li>
                  );
                })}
              </ol>
            </div>
          </section>
        ) : null}

        {/* ---------- Open findings (b-09 summary) ---------- */}
        <section aria-labelledby="findings-heading" className="mt-10">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2
                id="findings-heading"
                className="font-display text-2xl tracking-[-1.6px] md:text-[32px]"
              >
                Open findings
              </h2>
              <p className="mt-2 text-sm text-muted-foreground">
                Detected by the compliance scan across overtime basis, tip-pool
                composition, wage shortfalls, and notice coverage.
              </p>
            </div>
            {data.findings.length > 0 ? (
              <Link
                href="/violations"
                className={cn(buttonVariants(), "h-11 rounded-full px-6 text-base")}
              >
                Work all {data.findings.length} findings
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            ) : null}
          </div>

          {topFindings.length > 0 ? (
            <ol className="mt-5 grid gap-3">
              {topFindings.map((finding, index) => (
                <BlurFade as="li" key={finding.id} delay={index * 55}>
                  <Link
                    href="/violations"
                    className="group relative flex flex-col gap-4 overflow-hidden rounded-lg bg-card p-5 pl-6 transition-all duration-150 elev-1 hover:-translate-y-0.5 hover:ring-1 hover:ring-primary/30 md:flex-row md:items-center md:justify-between"
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        "absolute inset-y-0 left-0 w-[3px]",
                        SEVERITY_ACCENT[finding.severity].bar
                      )}
                    />
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-2">
                        <Badge
                          className={cn(
                            "rounded-sm font-mono text-[11px] tracking-[0.1em] uppercase",
                            SEVERITY_META[finding.severity].chipClass
                          )}
                        >
                          {SEVERITY_META[finding.severity].label}
                        </Badge>
                        <span className="eyebrow">
                          {finding.employeeName ?? "Roster-wide"} &middot; open{" "}
                          {finding.daysOpen}d
                        </span>
                      </span>
                      <span className="mt-2 block font-display text-xl leading-[1.15] tracking-[-1.2px]">
                        {RULE_CLASS_META[finding.ruleClass].title}
                      </span>
                      <span className="mt-1 block text-sm leading-[1.5] text-muted-foreground">
                        {RULE_CLASS_META[finding.ruleClass].fixAction}
                      </span>
                    </span>
                    <span className="shrink-0 md:pl-8 md:text-right">
                      <span className="eyebrow block">Exposure</span>
                      <span className="figure mt-1 block text-2xl leading-[1.1] md:text-3xl">
                        {exposureLabel(finding)}
                      </span>
                    </span>
                  </Link>
                </BlurFade>
              ))}
            </ol>
          ) : (
            <div className="mt-5 rounded-lg bg-card p-8 text-center elev-1 md:p-12">
              {hasRoster ? (
                <>
                  <span className="mx-auto flex size-14 items-center justify-center rounded-full bg-seal/10">
                    <ShieldCheck
                      className="size-7 text-seal dark:text-seal-soft"
                      aria-hidden="true"
                    />
                  </span>
                  <h3 className="mt-6 font-display text-2xl tracking-[-1.6px]">
                    Nothing flagged against this file
                  </h3>
                  <p className="mx-auto mt-3 max-w-lg text-sm leading-[1.55] text-muted-foreground">
                    The last scan came back clean. Keep the roster current and TipGuard
                    flags the next gap the moment it appears.
                  </p>
                </>
              ) : (
                <>
                  <Image
                    src="/images/empty-state.webp"
                    alt="An open file drawer holding a single empty folder"
                    width={400}
                    height={400}
                    className="mx-auto h-auto w-36 md:w-44"
                  />
                  <h3 className="mt-6 font-display text-2xl tracking-[-1.6px]">
                    Your file is empty
                  </h3>
                  <p className="mx-auto mt-3 max-w-lg text-sm leading-[1.55] text-muted-foreground">
                    Import your tipped staff and TipGuard can start checking overtime
                    basis, tip-pool composition, wage shortfalls, and notice coverage
                    against your own payroll data.
                  </p>
                </>
              )}
              <Link
                href={hasRoster ? "/violations" : "/staff"}
                className={cn(
                  buttonVariants(),
                  "mt-7 inline-flex h-11 rounded-full px-6 text-base"
                )}
              >
                {hasRoster ? "Review the scan history" : "Import your roster to start the file"}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
            </div>
          )}
        </section>

        {/* ---------- Monetize band (b-10) ---------- */}
        <section aria-labelledby="plan-heading" className="mt-10">
          <h2 id="plan-heading" className="sr-only">
            Your TipGuard plan
          </h2>
          <UpgradeCta
            noticesSent={data.notices.sent}
            openViolationCount={data.findings.length}
            exposureLabel={formatUsd(openExposure)}
            accountEmail={data.email}
          />
        </section>

        {/* ---------- Next actions ---------- */}
        <section aria-labelledby="actions-heading" className="mt-10">
          <h2
            id="actions-heading"
            className="font-display text-2xl tracking-[-1.6px] md:text-[32px]"
          >
            Keep the file current
          </h2>
          <Separator className="mt-5" />
          <ul className="mt-5 grid gap-4 md:grid-cols-3">
            <ActionCard
              index={0}
              href="/staff"
              icon={<UserPlus className="size-5" aria-hidden="true" />}
              title="Onboard a new hire"
              body="Add one employee and TipGuard generates their state-specific notice straight away — no need to re-import the whole roster."
            />
            <ActionCard
              index={1}
              href="/notices"
              icon={<FileSignature className="size-5" aria-hidden="true" />}
              title="Send notices for signature"
              body={
                outstandingNotices > 0
                  ? `${outstandingNotices} notice${
                      outstandingNotices === 1 ? "" : "s"
                    } are still waiting on a signature.`
                  : "Review every notice and its signature status in one list."
              }
            />
            <ActionCard
              index={2}
              href="/audit-file"
              icon={<ShieldCheck className="size-5" aria-hidden="true" />}
              title="Build the audit file"
              body="Assemble every signed notice, the status roster, and the violation log into one dated export."
            />
          </ul>
        </section>
      </div>
    </div>
  );
}

// --- Presentational pieces ---------------------------------------------------

function StatCard({
  index,
  label,
  value,
  sub,
  accent,
}: {
  index: number;
  label: string;
  value: string;
  sub: string;
  accent: string;
}) {
  return (
    <div
      // Tight 55ms stagger, per the visual brief's ledger-row rhythm.
      className="animate-in fade-in slide-in-from-bottom-2 fill-mode-both rounded-lg bg-card p-5 transition-all duration-150 elev-1 hover:-translate-y-0.5 hover:ring-1 hover:ring-primary/30"
      style={{ animationDelay: `${index * 55}ms` }}
    >
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-3">
        <span className={cn("figure block text-4xl leading-[1.1] md:text-5xl", accent)}>
          {value}
        </span>
        <span className="mt-3 block text-sm leading-[1.5] text-muted-foreground">
          {sub}
        </span>
      </dd>
    </div>
  );
}

function ActionCard({
  href,
  icon,
  title,
  body,
  index,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  body: string;
  index: number;
}) {
  return (
    // `mt-auto` on the Open row pins the three CTAs to one baseline regardless
    // of body length — the row reads as one system instead of three drafts.
    <BlurFade as="li" delay={index * 55} className="h-full">
      <Link
        href={href}
        className="group/action flex h-full flex-col rounded-lg bg-card p-5 transition-all duration-150 elev-1 hover:-translate-y-0.5 hover:ring-1 hover:ring-primary/30"
      >
        <span className="flex size-10 items-center justify-center rounded-md bg-primary/15 text-brass-deep transition-colors duration-150 group-hover/action:bg-primary/25 dark:text-primary">
          {icon}
        </span>
        <span className="mt-4 block font-display text-xl leading-[1.15] tracking-[-1.2px]">
          {title}
        </span>
        <span className="mt-2 block text-sm leading-[1.55] text-muted-foreground">
          {body}
        </span>
        <span className="mt-auto flex items-center gap-1 pt-5 text-sm font-medium text-brass-deep dark:text-primary">
          Open
          <ArrowRight
            className="size-4 transition-transform duration-150 group-hover/action:translate-x-0.5"
            aria-hidden="true"
          />
        </span>
      </Link>
    </BlurFade>
  );
}
