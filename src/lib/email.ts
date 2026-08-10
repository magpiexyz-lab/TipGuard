import { Resend } from "resend";

let _resend: Resend | null = null;

function getResend(): Resend {
  if (!_resend) {
    if (!process.env.RESEND_API_KEY) {
      throw new Error("RESEND_API_KEY is not configured");
    }
    _resend = new Resend(process.env.RESEND_API_KEY);
  }
  return _resend;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

function sanitizeSubject(str: string): string {
  return str.replace(/[\r\n\0]/g, "");
}

function safeUrl(url: string): string {
  if (url === "/" || (url.startsWith("/") && !url.startsWith("//"))) return url;
  if (url.startsWith("https://")) return url;
  throw new Error("Invalid URL: must be https:// or a relative path");
}

const FROM_ADDRESS = process.env.RESEND_FROM || "onboarding@resend.dev";

/**
 * Post-checkout welcome email (b-11) — sent by the Stripe webhook handler
 * after `checkout.session.completed` confirms the account is on Shield.
 * `to` and `ctaUrl` MUST be derived server-side (session email / static
 * origin path) — never accept either from client-controlled input, or this
 * becomes an open phishing relay from your verified Resend domain.
 */
export async function sendWelcomeEmail(to: string, restaurantName: string, ctaUrl: string) {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  if (process.env.DEMO_MODE === "true") return;
  const safeName = escapeHtml(restaurantName);
  const safeCtaUrl = safeUrl(ctaUrl);
  const { error } = await getResend().emails.send({
    from: FROM_ADDRESS,
    to,
    subject: `Welcome to TipGuard Shield, ${sanitizeSubject(restaurantName)}!`,
    html: `
      <h1>Welcome to TipGuard Shield, ${safeName}</h1>
      <p>Your account is protected — the audit-file export is unlocked and your tip-credit notice and violation history are now tracked continuously.</p>
      <p><a href="${safeCtaUrl}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;border-radius:6px;text-decoration:none;">Go to your dashboard</a></p>
    `,
  });
  if (error) throw error;
}

/**
 * Per-employee tip-credit notice signing-link email (b-06). `to` is the
 * employee's address on file; `signingUrl` is a single-use tokenized link
 * constructed server-side by the send-notice route — never accept either
 * value from client input.
 */
export async function sendNoticeSigningEmail(
  to: string,
  employeeName: string,
  employerName: string,
  signingUrl: string
) {
  if (process.env.DEMO_MODE === "true" && process.env.VERCEL === "1") {
    throw new Error("DEMO_MODE is not allowed in production");
  }
  if (process.env.DEMO_MODE === "true") return;
  const safeEmployeeName = escapeHtml(employeeName);
  const safeEmployerName = escapeHtml(employerName);
  const safeSigningUrl = safeUrl(signingUrl);
  const { error } = await getResend().emails.send({
    from: FROM_ADDRESS,
    to,
    subject: `Action needed: tip-credit notice from ${sanitizeSubject(employerName)}`,
    html: `
      <h1>Hi ${safeEmployeeName},</h1>
      <p>${safeEmployerName} has sent you a tip-credit notice that requires your signature. Please review it and sign to acknowledge.</p>
      <p><a href="${safeSigningUrl}" style="display:inline-block;padding:12px 24px;background:#2563eb;color:#fff;border-radius:6px;text-decoration:none;">Review and sign notice</a></p>
      <p style="color:#666;font-size:12px;">This link is single-use and will expire. If you did not expect this email, you can ignore it.</p>
    `,
  });
  if (error) throw error;
}
