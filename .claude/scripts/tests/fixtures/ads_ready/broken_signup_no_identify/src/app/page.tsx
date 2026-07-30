import { trackSignupComplete } from "@/lib/events";

export default function Page() {
  trackSignupComplete();
  return null;
}
