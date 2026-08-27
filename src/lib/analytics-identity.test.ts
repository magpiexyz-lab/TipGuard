import { describe, expect, it } from "vitest";
import { decideIdentityAction } from "./analytics-identity";

describe("decideIdentityAction", () => {
  describe("establishing identity", () => {
    it("identifies on SIGNED_IN when nobody has been identified yet", () => {
      const action = decideIdentityAction({
        event: "SIGNED_IN",
        userId: "user-abc",
        lastIdentifiedId: null,
      });
      expect(action).toEqual({ type: "identify", userId: "user-abc" });
    });

    it("identifies on INITIAL_SESSION when a session is restored on page load", () => {
      const action = decideIdentityAction({
        event: "INITIAL_SESSION",
        userId: "user-abc",
        lastIdentifiedId: null,
      });
      expect(action).toEqual({ type: "identify", userId: "user-abc" });
    });

    it("identifies again when a different account signs in", () => {
      const action = decideIdentityAction({
        event: "SIGNED_IN",
        userId: "user-second",
        lastIdentifiedId: "user-first",
      });
      expect(action).toEqual({ type: "identify", userId: "user-second" });
    });
  });

  describe("deduplication", () => {
    it("does nothing on a repeat SIGNED_IN for the already-identified user", () => {
      const action = decideIdentityAction({
        event: "SIGNED_IN",
        userId: "user-abc",
        lastIdentifiedId: "user-abc",
      });
      expect(action).toEqual({ type: "none" });
    });

    it("does nothing on INITIAL_SESSION for the already-identified user", () => {
      const action = decideIdentityAction({
        event: "INITIAL_SESSION",
        userId: "user-abc",
        lastIdentifiedId: "user-abc",
      });
      expect(action).toEqual({ type: "none" });
    });

    it("does nothing on TOKEN_REFRESHED for an already-identified user", () => {
      const action = decideIdentityAction({
        event: "TOKEN_REFRESHED",
        userId: "user-abc",
        lastIdentifiedId: "user-abc",
      });
      expect(action).toEqual({ type: "none" });
    });

    it("self-heals a missed identify when TOKEN_REFRESHED arrives unidentified", () => {
      const action = decideIdentityAction({
        event: "TOKEN_REFRESHED",
        userId: "user-abc",
        lastIdentifiedId: null,
      });
      expect(action).toEqual({ type: "identify", userId: "user-abc" });
    });
  });

  describe("sign-out", () => {
    it("resets on SIGNED_OUT when a user had been identified", () => {
      const action = decideIdentityAction({
        event: "SIGNED_OUT",
        userId: null,
        lastIdentifiedId: "user-abc",
      });
      expect(action).toEqual({ type: "reset" });
    });

    it("does nothing on SIGNED_OUT when nobody was ever identified", () => {
      // Resetting here would churn the anonymous distinct_id for no gain.
      const action = decideIdentityAction({
        event: "SIGNED_OUT",
        userId: null,
        lastIdentifiedId: null,
      });
      expect(action).toEqual({ type: "none" });
    });
  });

  describe("anonymous visitor guard", () => {
    // The whole point of this change is to PRESERVE the anonymous distinct_id
    // long enough to merge it into the user id. It carries the gclid/utm_*
    // super-properties registered by the `loaded` callback in analytics.ts.
    // A reset on an anonymous landing visit would destroy exactly that.
    it("does nothing on INITIAL_SESSION with no session — never resets", () => {
      const action = decideIdentityAction({
        event: "INITIAL_SESSION",
        userId: null,
        lastIdentifiedId: null,
      });
      expect(action).toEqual({ type: "none" });
    });

    it("does not reset an anonymous visitor when userId is undefined", () => {
      const action = decideIdentityAction({
        event: "INITIAL_SESSION",
        userId: undefined,
        lastIdentifiedId: null,
      });
      expect(action).toEqual({ type: "none" });
    });

    it("treats an empty-string user id as no session", () => {
      const action = decideIdentityAction({
        event: "SIGNED_IN",
        userId: "",
        lastIdentifiedId: null,
      });
      expect(action).toEqual({ type: "none" });
    });
  });

  describe("unenumerated Supabase events", () => {
    it("identifies on USER_UPDATED when the id is not yet identified", () => {
      const action = decideIdentityAction({
        event: "USER_UPDATED",
        userId: "user-abc",
        lastIdentifiedId: null,
      });
      expect(action).toEqual({ type: "identify", userId: "user-abc" });
    });

    it("does nothing on PASSWORD_RECOVERY for the already-identified user", () => {
      const action = decideIdentityAction({
        event: "PASSWORD_RECOVERY",
        userId: "user-abc",
        lastIdentifiedId: "user-abc",
      });
      expect(action).toEqual({ type: "none" });
    });
  });
});
