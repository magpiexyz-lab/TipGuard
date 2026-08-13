import { ImageResponse } from "next/og";

export const size = { width: 128, height: 128 };
export const contentType = "image/png";

// Token values are inlined rather than read from globals.css: Satori has no
// CSS-variable resolution, and fetching a font/stylesheet here would add a
// network dependency to the icon route.
const INK = "#171C13";
const BRASS = "#C89230";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: INK,
          borderRadius: 24,
        }}
      >
        <div
          style={{
            fontSize: 76,
            fontWeight: 700,
            color: BRASS,
            fontFamily: "serif",
            letterSpacing: -4,
            display: "flex",
          }}
        >
          T
        </div>
      </div>
    ),
    { ...size }
  );
}
