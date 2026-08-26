import type { Metadata } from "next";

import { SessionGate } from "@/components/auth/session-gate";
import { ConsoleShell } from "@/components/console/console-shell";

export const metadata: Metadata = {
  title: { default: "Dashboard", template: "%s · Fvas" },
  // The console has no SEO value and must never be indexed.
  robots: { index: false, follow: false },
};

/**
 * Console shell.
 *
 * `SessionGate` wraps the whole group, so every page below is guaranteed an
 * authenticated principal — no page has to guard itself, and none can forget.
 */
export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionGate>
      <ConsoleShell>{children}</ConsoleShell>
    </SessionGate>
  );
}
