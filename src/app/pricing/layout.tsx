import type { Metadata } from "next";

const title = "Pricing — $79/mo Against a Six-Figure Wage Claim | TipGuard";
const description =
  "TipGuard Shield is $79 a month. See the tip-credit back-pay arithmetic it stands against, and exactly what the free tier keeps.";

export const metadata: Metadata = {
  title,
  description,
  openGraph: { title, description, url: "/pricing" },
  twitter: { card: "summary_large_image", title, description },
  alternates: { canonical: "/pricing" },
};

export default function PricingLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
