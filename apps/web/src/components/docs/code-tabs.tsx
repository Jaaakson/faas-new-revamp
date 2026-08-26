"use client";

import * as React from "react";
import { Check, Copy } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * One request, four languages.
 *
 * The chosen language is stored in `localStorage` and shared by every block on
 * the site. A Go developer reading the enrollment guide should not have to click
 * "Go" on each of nine examples — the second click is the one that makes docs
 * feel careless.
 *
 * Rendering is deliberately plain `<pre>` rather than the Shiki pipeline used
 * for prose code blocks: these samples are interactive (tabs, copy) and go
 * through a client component, while Shiki highlights at build time on the
 * server. Trading syntax colour for a working language switcher is the right
 * way round — a developer copies these, they do not admire them.
 */

const STORAGE_KEY = "fvas.docs.language";

export interface CodeSample {
  language: string;
  label: string;
  code: string;
}

export function CodeTabs({ samples }: { samples: CodeSample[] }) {
  const [active, setActive] = React.useState(samples[0]?.language ?? "");
  const [copied, setCopied] = React.useState(false);

  // Read the shared preference after mount. Doing it during render would
  // produce server/client HTML that disagrees, and Next would throw a
  // hydration error on every docs page.
  React.useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored && samples.some((sample) => sample.language === stored)) {
      setActive(stored);
    }
  }, [samples]);

  // Keep every block on the page in step, including ones mounted later.
  React.useEffect(() => {
    const onChange = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      if (samples.some((sample) => sample.language === detail)) setActive(detail);
    };
    window.addEventListener("fvas:language", onChange);
    return () => window.removeEventListener("fvas:language", onChange);
  }, [samples]);

  const choose = (language: string) => {
    setActive(language);
    window.localStorage.setItem(STORAGE_KEY, language);
    window.dispatchEvent(new CustomEvent("fvas:language", { detail: language }));
  };

  const current = samples.find((sample) => sample.language === active) ?? samples[0];

  const copy = async () => {
    if (!current) return;
    try {
      await navigator.clipboard.writeText(current.code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard can be refused; the text is selectable either way.
    }
  };

  if (!current) return null;

  return (
    <div className="mt-6 overflow-hidden rounded-lg border">
      <div className="bg-muted/50 flex items-center justify-between border-b">
        <div role="tablist" aria-label="Code language" className="flex">
          {samples.map((sample) => (
            <button
              key={sample.language}
              role="tab"
              type="button"
              aria-selected={sample.language === current.language}
              onClick={() => choose(sample.language)}
              className={cn(
                "focus-visible:ring-ring border-b-2 px-3 py-2 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none",
                sample.language === current.language
                  ? "border-primary text-foreground"
                  : "text-muted-foreground hover:text-foreground border-transparent",
              )}
            >
              {sample.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => void copy()}
          aria-label="Copy code"
          className="text-muted-foreground hover:text-foreground focus-visible:ring-ring mr-2 rounded p-1.5 focus-visible:ring-2 focus-visible:outline-none"
        >
          {copied ? (
            <Check className="size-3.5 text-emerald-500" aria-hidden />
          ) : (
            <Copy className="size-3.5" aria-hidden />
          )}
          <span className="sr-only">{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>

      <pre className="overflow-x-auto p-4 text-xs leading-relaxed">
        <code>{current.code}</code>
      </pre>
    </div>
  );
}
