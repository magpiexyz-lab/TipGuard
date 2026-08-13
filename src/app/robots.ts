import type { MetadataRoute } from "next";

const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ?? "http://localhost:3000";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Tokenized signing links and authenticated surfaces must never be
      // indexed — /sign URLs carry a single-use signature token.
      disallow: ["/api/", "/sign", "/auth/"],
    },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
