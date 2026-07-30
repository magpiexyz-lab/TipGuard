import { track } from "./analytics";

export function trackLandingViewed() {
  track("landing_viewed");
}

export function trackSignupComplete() {
  track("signup_complete");
}
