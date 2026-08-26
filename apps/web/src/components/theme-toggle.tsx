"use client";

import * as React from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

const ORDER = ["light", "dark", "system"] as const;

const ICONS = {
  light: Sun,
  dark: Moon,
  system: Monitor,
} as const;

/**
 * Cycles light → dark → system.
 *
 * Renders a placeholder until mounted: the server cannot know the resolved
 * theme, so rendering the real icon immediately guarantees a hydration
 * mismatch. The placeholder holds the exact same box, so nothing shifts.
 */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className="size-9" aria-hidden />;
  }

  const current = (ORDER.find((value) => value === theme) ?? "system") as (typeof ORDER)[number];
  const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length]!;
  const Icon = ICONS[current];

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(next)}
      aria-label={`Theme: ${current}. Switch to ${next}.`}
      title={`Theme: ${current}`}
    >
      <Icon />
    </Button>
  );
}
