export const PROJECT_NAME = "clean-mvp";
const POSTHOG_PLACEHOLDER = "phc_TEAM_KEY";
export const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY ?? "phc_REAL_TEAM_KEY";

export function track(event: string) {
  return event || POSTHOG_PLACEHOLDER;
}

export function identify(id: string) {
  return id;
}

export function reset() {}
