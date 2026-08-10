import { describe, expect, it } from "vitest";
import { classifyVisit } from "./analytics-attribution";

describe("classifyVisit", () => {
  it("matches a reddit.com/r/restaurateur referrer", () => {
    const result = classifyVisit({ referrer: "https://www.reddit.com/r/restaurateur/comments/abc123" });
    expect(result.qualified).toBe(true);
    expect(result.sourceChannel).toBe("reddit_restaurateur");
  });

  it("matches a state restaurant association domain referrer", () => {
    const result = classifyVisit({ referrer: "https://www.restaurant.org/news/tip-credit" });
    expect(result.qualified).toBe(true);
    expect(result.sourceChannel).toBe("association");
  });

  it("matches a Meta restaurant-owner ad campaign", () => {
    const result = classifyVisit({ utmSource: "meta", utmMedium: "cpc", utmCampaign: "restaurant-owner-tip-credit" });
    expect(result.qualified).toBe(true);
    expect(result.sourceChannel).toBe("meta_restaurant");
  });

  it("matches a Google search-intent campaign", () => {
    const result = classifyVisit({ utmSource: "google", utmMedium: "cpc", utmCampaign: "tip-credit-notice" });
    expect(result.qualified).toBe(true);
    expect(result.sourceChannel).toBe("google_intent");
  });

  it("does not match direct traffic with no UTM or referrer", () => {
    const result = classifyVisit({});
    expect(result.qualified).toBe(false);
    expect(result.sourceChannel).toBeNull();
  });

  it("does not match generic organic search traffic", () => {
    const result = classifyVisit({ referrer: "https://www.google.com/search?q=restaurant+software" });
    expect(result.qualified).toBe(false);
    expect(result.sourceChannel).toBeNull();
  });

  it("classifies unmatched paid traffic as other_paid, not qualified", () => {
    const result = classifyVisit({ utmSource: "facebook", utmMedium: "cpc", utmCampaign: "generic-brand-awareness" });
    expect(result.qualified).toBe(false);
    expect(result.sourceChannel).toBe("other_paid");
  });
});
