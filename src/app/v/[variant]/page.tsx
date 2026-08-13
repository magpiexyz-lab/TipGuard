import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Landing } from "@/components/landing/landing";
import { VARIANT_SLUGS, getVariant } from "@/lib/variants";

// Variant set is fixed at build time — prerender all three.
export function generateStaticParams() {
  return VARIANT_SLUGS.map((variant) => ({ variant }));
}

export const dynamicParams = false;

export async function generateMetadata({
  params,
}: {
  params: Promise<{ variant: string }>;
}): Promise<Metadata> {
  const { variant: slug } = await params;
  const variant = getVariant(slug);
  if (!variant) return {};

  return {
    title: variant.metaTitle,
    description: variant.metaDescription,
    openGraph: {
      title: variant.metaTitle,
      description: variant.metaDescription,
    },
    twitter: {
      title: variant.metaTitle,
      description: variant.metaDescription,
    },
  };
}

export default async function VariantPage({
  params,
}: {
  params: Promise<{ variant: string }>;
}) {
  const { variant: slug } = await params;
  const variant = getVariant(slug);
  if (!variant) notFound();

  return <Landing variant={variant} />;
}
