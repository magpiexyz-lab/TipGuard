import { randomBytes } from "node:crypto";
import { NextResponse } from "next/server";
import { z } from "zod";
import { resolveAccount } from "@/lib/api-auth";
import { rateLimit, clientIpFromHeaders } from "@/lib/rate-limit";
import { sendNoticeSigningEmail } from "@/lib/email";
import type { EmployeeRow, NoticeRow } from "@/lib/types";
import type { SendBlock, SendDispatch } from "@/app/notices/notice-types";
// CROSS-AGENT CONTRACT (src/app/sign/signing-token.ts, top-of-file note):
// the route that MINTS tokens and the route that CONSUMES them must use the
// same digest function. This import — not a second createHash("sha256") call
// in this file — is what guarantees that. Forking the implementation would
// break every signing link in production, silently, at consume time.
import { hashSigningToken } from "@/app/sign/signing-token";

export const dynamic = "force-dynamic";

/** How long a signing link stays live. Long enough for a next-shift employee. */
const TOKEN_TTL_MS = 14 * 24 * 60 * 60 * 1000;

export const sendNoticesSchema = z.object({
  notice_ids: z.array(z.uuid()).min(1).max(200),
});

export type SendNoticesResponse = {
  sent: SendDispatch[];
  blocked: SendBlock[];
  delivery_channel: "email" | "link_copy";
};

type SendableNotice = Pick<
  NoticeRow,
  "id" | "account_id" | "employee_id" | "status" | "notice_text"
>;

export async function POST(request: Request) {
  // Not an auth or payment route, but it dispatches email on demand — an
  // unthrottled loop here is an outbound-spam vector against our Resend domain.
  const ip = clientIpFromHeaders(request.headers);
  const { success } = rateLimit(`notices-send:${ip}`, { limit: 20, windowMs: 60_000 });
  if (!success) {
    return NextResponse.json({ error: "Too many requests" }, { status: 429 });
  }
  // TODO: Upgrade to Upstash Redis for cross-instance rate limiting

  let input: z.infer<typeof sendNoticesSchema>;
  try {
    input = sendNoticesSchema.parse(await request.json());
  } catch {
    return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  }

  const resolved = await resolveAccount();
  if (!resolved.ok) {
    if (resolved.reason === "unauthenticated") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    if (resolved.reason === "no_account") {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }
    return NextResponse.json({ error: "Service unavailable" }, { status: 503 });
  }
  const { account, db } = resolved.ctx;

  // MEASUREMENT GUARD: dedupe before anything is minted or mailed. `/notices`
  // fires `notice_sent` once per entry in the `sent[]` array below, with
  // employee_count = sent.length — so a repeated id (double-submit, or a
  // "send all" over a list that already contains the row) would double-count
  // the experiment's activation event (h-04 numerator), mail the employee the
  // same notice twice, and leave two live tokens on one notice. Set preserves
  // insertion order, so the response still mirrors the requested order.
  const noticeIds = [...new Set(input.notice_ids)];

  // STATE-TRANSITION GUARD (wire.md Step 5): `status` is in the SELECT so the
  // pre-state can be checked before the mutation. `notices.status` is a
  // draft -> sent -> signed DAG; b-06 requires that re-sending a SIGNED notice
  // is blocked with a clear message, because a signature is an immutable
  // record of a specific text.
  const { data, error } = await db
    .from("notices")
    .select("id, account_id, employee_id, status, notice_text")
    .eq("account_id", account.id)
    .in("id", noticeIds);

  if (error) {
    console.error("[notices/send] Supabase error:", error);
    return NextResponse.json({ error: "Could not send notices" }, { status: 500 });
  }

  const found = (data ?? []) as SendableNotice[];
  const foundById = new Map(found.map((notice) => [notice.id, notice]));

  const employeeIds = found.map((notice) => notice.employee_id);
  const employeesResult = employeeIds.length
    ? await db
        .from("employees")
        .select("id, name, email, role")
        .eq("account_id", account.id)
        .in("id", employeeIds)
    : { data: [], error: null };
  // A swallowed error here yields an EMPTY employee map, and every notice is
  // then refused with "this employee has no email address on file" — telling
  // the owner to repair a roster that is not broken while a database fault
  // goes unreported. A lookup failure is infrastructure, not user data.
  if (employeesResult.error) {
    console.error("[notices/send] employee lookup failed:", employeesResult.error);
    return NextResponse.json({ error: "Could not send notices" }, { status: 500 });
  }
  const employeeById = new Map(
    ((employeesResult.data ?? []) as Pick<
      EmployeeRow,
      "id" | "name" | "email" | "role"
    >[]).map((employee) => [employee.id, employee])
  );

  const employerName = account.restaurant_name || "Your employer";
  const siteUrl = (
    process.env.NEXT_PUBLIC_SITE_URL ?? new URL(request.url).origin
  ).replace(/\/$/, "");

  const sent: SendDispatch[] = [];
  const blocked: SendBlock[] = [];
  let anyEmailDelivered = false;
  let anyEmailFailed = false;

  for (const noticeId of noticeIds) {
    const notice = foundById.get(noticeId);
    if (!notice) {
      // Uniform "not yours / does not exist" — never confirm existence of a
      // row outside the caller's account.
      blocked.push({ notice_id: noticeId, reason: "This notice is no longer available." });
      continue;
    }

    if (notice.status === "signed") {
      blocked.push({
        notice_id: noticeId,
        reason:
          "This notice has already been signed. A signed acknowledgment is an immutable record and cannot be re-sent.",
      });
      continue;
    }

    const employee = employeeById.get(notice.employee_id);
    if (!employee?.email) {
      blocked.push({
        notice_id: noticeId,
        reason: "This employee has no email address on file. Add one and re-send.",
      });
      continue;
    }

    // 32 random bytes, base64url — 43 chars, matches SIGNING_TOKEN_PATTERN.
    // Only the SHA-256 digest is persisted; the raw token exists solely in the
    // email we are about to dispatch.
    const rawToken = randomBytes(32).toString("base64url");
    const expiresAt = new Date(Date.now() + TOKEN_TTL_MS).toISOString();

    const tokenResult = await db.from("signing_tokens").insert({
      account_id: account.id,
      notice_id: notice.id,
      token_hash: hashSigningToken(rawToken),
      expires_at: expiresAt,
    });
    if (tokenResult.error) {
      console.error("[notices/send] token insert failed:", tokenResult.error);
      blocked.push({
        notice_id: noticeId,
        reason: "The signing link could not be created. Nothing was sent — try again.",
      });
      continue;
    }

    const statusResult = await db
      .from("notices")
      .update({ status: "sent", sent_at: new Date().toISOString() })
      .eq("id", notice.id)
      .eq("account_id", account.id);
    if (statusResult.error) {
      console.error("[notices/send] status update failed:", statusResult.error);
      blocked.push({
        notice_id: noticeId,
        reason: "The notice status could not be updated. Try again.",
      });
      continue;
    }

    try {
      await sendNoticeSigningEmail(
        employee.email,
        employee.name,
        employerName,
        `${siteUrl}/sign?token=${encodeURIComponent(rawToken)}`
      );
      anyEmailDelivered = true;
    } catch (emailError) {
      // The token exists and the notice is 'sent' — the link is real even
      // though delivery failed. Report the channel honestly rather than
      // pretending an email went out.
      console.error("[notices/send] email dispatch failed:", emailError);
      anyEmailFailed = true;
    }

    sent.push({ notice_id: notice.id, expires_at: expiresAt });
  }

  // Every requested notice was refused → the whole transition was invalid.
  if (sent.length === 0 && blocked.length > 0) {
    return NextResponse.json(
      {
        sent,
        blocked,
        delivery_channel: "email",
        error: "No notice could be sent",
      },
      { status: 409 }
    );
  }

  return NextResponse.json({
    sent,
    blocked,
    delivery_channel: anyEmailDelivered || !anyEmailFailed ? "email" : "link_copy",
  } satisfies SendNoticesResponse);
}
