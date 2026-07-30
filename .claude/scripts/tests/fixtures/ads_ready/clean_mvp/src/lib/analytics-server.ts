export const PROJECT_NAME = "clean-mvp";
const POSTHOG_PLACEHOLDER = "phc_TEAM_KEY";
export const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "phc_REAL_TEAM_KEY";

export function trackServerEvent(event: string) {
  return event || POSTHOG_PLACEHOLDER;
}
