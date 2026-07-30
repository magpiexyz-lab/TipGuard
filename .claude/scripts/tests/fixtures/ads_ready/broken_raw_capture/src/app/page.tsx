import posthog from "posthog-js";

export default function Page() {
  posthog.capture("landing_viewed");
  return null;
}
