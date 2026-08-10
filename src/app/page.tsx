import { Landing } from "@/components/landing/landing";
import { VARIANTS, DEFAULT_VARIANT } from "@/lib/variants";

// Root renders the default variant directly (no redirect) so paid traffic
// landing on `/` is not charged an extra hop.
export default function Page() {
  return <Landing variant={VARIANTS[DEFAULT_VARIANT]} />;
}
