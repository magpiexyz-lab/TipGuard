import { identify } from "@/lib/analytics";
import { trackLandingViewed, trackSignupComplete } from "@/lib/events";

export function LandingHero() {
  trackLandingViewed();
  identify("user_123");
  trackSignupComplete();
  return null;
}
