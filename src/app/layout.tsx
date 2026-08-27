import type { Metadata } from "next";
import Script from "next/script";
import { Fraunces, IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { VARIANTS, DEFAULT_VARIANT } from "@/lib/variants";
// Wired by scaffold-wire (wire.md Step 5c), after every component existed.
import { NavBar } from "@/components/nav-bar";
import { RetainTracker } from "@/components/RetainTracker";
import { PendingScoreClaim } from "@/components/pending-score-claim";
import { AnalyticsIdentity } from "@/components/analytics-identity";
import { FeedbackWidget } from "@/components/feedback-widget";

// Font variables MUST be bound on <html>, not <body> — the :root-scoped rules
// in globals.css resolve empty otherwise and every page falls back to Times.
const fraunces = Fraunces({
  subsets: ["latin"],
  axes: ["SOFT", "WONK", "opsz"],
  variable: "--font-fraunces",
  display: "swap",
});

const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

const defaultVariant = VARIANTS[DEFAULT_VARIANT];

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: defaultVariant.metaTitle,
  description: defaultVariant.metaDescription,
  applicationName: "TipGuard",
  openGraph: {
    type: "website",
    siteName: "TipGuard",
    title: defaultVariant.metaTitle,
    description: defaultVariant.metaDescription,
    url: siteUrl,
  },
  twitter: {
    card: "summary_large_image",
    title: defaultVariant.metaTitle,
    description: defaultVariant.metaDescription,
  },
};

// JSON-LD WebApplication schema — web-app archetype convention.
const jsonLd = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "TipGuard",
  url: siteUrl,
  applicationCategory: "BusinessApplication",
  operatingSystem: "Web",
  description: defaultVariant.metaDescription,
  offers: {
    "@type": "Offer",
    price: String(defaultVariant.pricingAmount),
    priceCurrency: "USD",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${plexSans.variable} ${plexMono.variable}`}
    >
      <body className="min-h-screen bg-background text-foreground antialiased texture-grain">
        {/* Paid-attribution capture. `beforeInteractive` hoists this into
            <head> and guarantees it runs BEFORE React hydration, so `?gclid=`
            is read from the URL even when the Next.js router later strips the
            query string via replaceState. The `loaded` callback in
            analytics.ts reads these sessionStorage keys back and registers
            them as PostHog super-properties. */}
        <Script id="capture-paid-attribution" strategy="beforeInteractive">
          {`
            try {
              var p = new URLSearchParams(window.location.search);
              var g = p.get('gclid');
              // Match the /iterate --cross filter at the source: only stamp
              // gclids that look real (length > 40, prefix in {Cj, EAI, CIa}).
              // Operator test gclids never enter the analytics pipeline.
              if (g && g.length > 40 && /^(Cj|EAI|CIa)/.test(g)) {
                sessionStorage.setItem('__ph_gclid', g);
              }
              ['utm_source','utm_medium','utm_campaign','utm_content','utm_term'].forEach(function(k){
                var v = p.get(k);
                if (v) sessionStorage.setItem('__ph_' + k, v);
              });
            } catch (e) {
              // sessionStorage unavailable (private mode, sandboxed iframe); skip
            }
          `}
        </Script>
        <script
          type="application/ld+json"
          // Static, non-user-derived schema object — safe to inline.
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
        />
        {/* WCAG 2.4.1 (Bypass Blocks): skip link, matching id, and
            tabIndex={-1} on the target are all three required. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-background focus:px-4 focus:py-2 focus:text-foreground"
        >
          Skip to main content
        </a>
        <NavBar />
        {/* SINGLE SOURCE OF THE `main` LANDMARK.
            layout.tsx owns exactly one <main> for every route in the app. No
            page component may render its own — two <main> elements on one page
            fail axe `landmark-no-duplicate-main`, and zero fail
            `landmark-one-main`. login, signup, error, not-found and
            auth/reset-password were each rendering their own; scaffold-wire
            demoted all five to <div> when it added this wrapper. */}
        <main id="main-content" tabIndex={-1}>
          {children}
        </main>
        <PendingScoreClaim />
        {/* Calls identify(user.id) once a Supabase session exists, so PostHog
            merges the anonymous pre-signup distinct_id (which carries gclid /
            utm_*) into the signed-in user id that server-side signup_complete
            reports against. Mounted here because no single page sees every
            session-establishing path — Google OAuth returns through a server
            route, so nothing on the page side can do this. */}
        <AnalyticsIdentity />
        <FeedbackWidget />
        <RetainTracker />
      </body>
    </html>
  );
}
