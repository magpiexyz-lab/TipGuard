import { ImageResponse } from "next/og";
import { VARIANTS, DEFAULT_VARIANT } from "@/lib/variants";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "TipGuard — tip-credit compliance for restaurants";

// Inlined tokens — Satori cannot resolve CSS variables.
const INK = "#171C13";
const PAPER = "#F3F0E6";
const BRASS = "#C89230";
const MUTED = "#A8AF9B";

export default function OpengraphImage() {
  const variant = VARIANTS[DEFAULT_VARIANT];

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: INK,
          padding: 72,
          // Ruled ledger hairlines at the 32px rhythm, per the visual brief.
          backgroundImage: `linear-gradient(to bottom, rgba(243,240,230,0.06) 1px, transparent 1px)`,
          backgroundSize: "100% 32px",
        }}
      >
        <div
          style={{
            display: "flex",
            fontSize: 22,
            fontFamily: "monospace",
            letterSpacing: 3,
            color: BRASS,
            textTransform: "uppercase",
          }}
        >
          TipGuard — Tip-Credit Compliance
        </div>

        <div style={{ display: "flex", flexDirection: "column" }}>
          <div
            style={{
              display: "flex",
              fontSize: 64,
              fontWeight: 700,
              fontFamily: "serif",
              color: PAPER,
              letterSpacing: -2,
              lineHeight: 1.05,
              maxWidth: 980,
            }}
          >
            {variant.headline}
          </div>

          {/* Brass rule with a stamp tick */}
          <div style={{ display: "flex", alignItems: "center", marginTop: 40 }}>
            <div style={{ display: "flex", width: 180, height: 2, background: BRASS }} />
            <div style={{ display: "flex", width: 6, height: 6, background: BRASS, marginLeft: 6 }} />
          </div>

          <div
            style={{
              display: "flex",
              marginTop: 28,
              fontSize: 26,
              color: MUTED,
              maxWidth: 900,
              lineHeight: 1.4,
            }}
          >
            {variant.promise}
          </div>
        </div>
      </div>
    ),
    { ...size }
  );
}
