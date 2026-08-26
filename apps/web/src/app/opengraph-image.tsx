import { ImageResponse } from "next/og";

export const alt = "Fvas — Face authentication, three API calls away.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Social preview card, generated at build time.
 *
 * Generated rather than a checked-in PNG so the copy cannot drift from the
 * product. Only core system fonts and inline styles are available in this
 * runtime — no Tailwind, no design tokens — so the palette is duplicated here
 * deliberately, matching the dark theme in globals.css.
 */
export default function OpengraphImage() {
  return new ImageResponse(
    <div
      style={{
        height: "100%",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        background: "#020617",
        padding: 72,
        fontFamily: "sans-serif",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            background: "#818cf8",
            display: "flex",
          }}
        />
        <span style={{ color: "#f8fafc", fontSize: 34, fontWeight: 600 }}>Fvas</span>
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ color: "#f8fafc", fontSize: 68, fontWeight: 600, lineHeight: 1.1 }}>
          Face authentication,
        </div>
        <div style={{ color: "#818cf8", fontSize: 68, fontWeight: 600, lineHeight: 1.1 }}>
          three API calls away.
        </div>
        <div style={{ color: "#94a3b8", fontSize: 28, marginTop: 24, maxWidth: 900 }}>
          Enroll a face. Verify in under a second. Get an audit trail your compliance team will
          accept.
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          borderTop: "1px solid #1e293b",
          paddingTop: 28,
        }}
      >
        <span style={{ color: "#64748b", fontSize: 24 }}>POST /v1/verifications</span>
        <span style={{ color: "#34d399", fontSize: 24 }}>verified · 0.8121 · 284 ms</span>
      </div>
    </div>,
    size,
  );
}
