import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  env: {
    // Vercel does NOT auto-prefix system env vars with NEXT_PUBLIC_.
    // The `?? ""` keeps the value defined-but-empty off-Vercel so client-side
    // `=== "production"` gates fall through to non-production code paths.
    NEXT_PUBLIC_VERCEL_ENV: process.env.VERCEL_ENV ?? "",
  },
  async rewrites() {
    return [
      { source: "/ingest/decide", destination: "https://us.i.posthog.com/decide" },
      { source: "/ingest/:path*", destination: "https://us.i.posthog.com/:path*" },
    ];
  },
  // `/sign` renders a form that produces an immutable legal record, so it must
  // not be frameable — an overlay on an attacker page could harvest a real
  // signature. Referrer-Policy is defence in depth for the same page: the
  // signing link carries a token in its query string, and a full referrer would
  // hand it to any third-party asset host.
  // Deliberately NOT a full script-src CSP: PostHog and Next's inline bootstrap
  // both need nonce plumbing that is not worth the regression risk right now.
  // frame-ancestors is the directive that closes the finding.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
  skipTrailingSlashRedirect: true,
};

export default nextConfig;
